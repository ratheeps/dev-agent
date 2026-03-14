provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project     = var.project
      environment = var.environment
      managed_by  = "opentofu"
    }
  }
}

# -----------------------------------------------------
# Lightsail Instance
# -----------------------------------------------------

resource "aws_lightsail_instance" "mason" {
  name              = "${var.project}-${var.environment}"
  availability_zone = "${var.aws_region}a"
  blueprint_id      = var.instance_blueprint
  bundle_id         = var.instance_bundle
  key_pair_name     = var.ssh_key_name

  user_data = file("${path.module}/user-data.sh")

  tags = {
    component = "runtime"
  }
}

resource "aws_lightsail_static_ip" "mason" {
  name = "${var.project}-${var.environment}-ip"
}

resource "aws_lightsail_static_ip_attachment" "mason" {
  static_ip_name = aws_lightsail_static_ip.mason.name
  instance_name  = aws_lightsail_instance.mason.name
}

# Firewall: allow SSH + HTTPS + webhook port
resource "aws_lightsail_instance_public_ports" "mason" {
  instance_name = aws_lightsail_instance.mason.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
  }

  port_info {
    protocol  = "tcp"
    from_port = 8000
    to_port   = 8000
  }
}

# -----------------------------------------------------
# DynamoDB Tables (pay-per-request — essentially free)
# -----------------------------------------------------

resource "aws_dynamodb_table" "session_memory" {
  name         = "${var.project}-session-memory"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "timestamp"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  attribute {
    name = "agent_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false # Disable for eval — saves cost
  }

  global_secondary_index {
    name            = "agent_id-index"
    hash_key        = "agent_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  tags = { component = "memory" }
}

resource "aws_dynamodb_table" "episodic_memory" {
  name         = "${var.project}-episodic-memory"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "agent_id"
  range_key    = "episode_id"

  attribute {
    name = "agent_id"
    type = "S"
  }

  attribute {
    name = "episode_id"
    type = "S"
  }

  attribute {
    name = "task_id"
    type = "S"
  }

  global_secondary_index {
    name            = "task_id-index"
    hash_key        = "task_id"
    range_key       = "episode_id"
    projection_type = "ALL"
  }

  tags = { component = "memory" }
}

resource "aws_dynamodb_table" "semantic_memory" {
  name         = "${var.project}-semantic-memory"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "namespace"
  range_key    = "key"

  attribute {
    name = "namespace"
    type = "S"
  }

  attribute {
    name = "key"
    type = "S"
  }

  tags = { component = "memory" }
}

# -----------------------------------------------------
# SQS Task Queue + DLQ (free tier — 1M requests/mo)
# -----------------------------------------------------

resource "aws_sqs_queue" "tasks_dlq" {
  name                      = "${var.project}-tasks-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = { component = "queue" }
}

resource "aws_sqs_queue" "tasks" {
  name                       = "${var.project}-tasks"
  visibility_timeout_seconds = 28800
  message_retention_seconds  = 1209600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.tasks_dlq.arn
    maxReceiveCount     = 2
  })

  tags = { component = "queue" }
}

resource "aws_sqs_queue_redrive_allow_policy" "tasks_dlq" {
  queue_url = aws_sqs_queue.tasks_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.tasks.arn]
  })
}

# -----------------------------------------------------
# IAM Role for the Lightsail instance
# -----------------------------------------------------

resource "aws_iam_role" "mason_instance" {
  name = "${var.project}-${var.environment}-lightsail"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lightsail.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "mason_instance" {
  name = "${var.project}-${var.environment}-lightsail-policy"
  role = aws_iam_role.mason_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchWriteItem",
          "dynamodb:BatchGetItem",
        ]
        Resource = [
          aws_dynamodb_table.session_memory.arn,
          "${aws_dynamodb_table.session_memory.arn}/index/*",
          aws_dynamodb_table.episodic_memory.arn,
          "${aws_dynamodb_table.episodic_memory.arn}/index/*",
          aws_dynamodb_table.semantic_memory.arn,
          "${aws_dynamodb_table.semantic_memory.arn}/index/*",
        ]
      },
      {
        Sid    = "SQS"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:SendMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = [
          aws_sqs_queue.tasks.arn,
          aws_sqs_queue.tasks_dlq.arn,
        ]
      },
      {
        Sid    = "Bedrock"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = ["*"]
      },
    ]
  })
}
