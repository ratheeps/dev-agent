# ECS Fargate cluster, task definitions, services, and auto-scaling
# Replaces the previous Bedrock AgentCore IAM-only stub

data "aws_caller_identity" "current" {}

# -----------------------------------------------------
# ECS Cluster
# -----------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { component = "runtime" }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# -----------------------------------------------------
# IAM — Task Execution Role (ECR pull, logs, secrets)
# -----------------------------------------------------

resource "aws_iam_role" "ecs_execution" {
  name        = "${var.project}-ecs-execution-role"
  description = "ECS task execution role — ECR pull, CloudWatch logs, Secrets Manager read"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { component = "runtime" }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.project}-ecs-execution-secrets"
  description = "Allow ECS execution role to read secrets for container env injection"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
      ]
      Resource = [
        "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# -----------------------------------------------------
# IAM — Orchestrator Task Role (Bedrock, DynamoDB, SQS, etc.)
# -----------------------------------------------------

resource "aws_iam_role" "orchestrator" {
  name        = "${var.project}-orchestrator-role"
  description = "Task role for the Mason Opus orchestrator agent"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# IAM — Worker Task Role
# -----------------------------------------------------

resource "aws_iam_role" "worker" {
  name        = "${var.project}-worker-role"
  description = "Task role for Mason Sonnet worker agents"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Shared Agent Policy (Bedrock, DynamoDB, Secrets, Logs, SQS)
# -----------------------------------------------------

resource "aws_iam_policy" "agent_policy" {
  name        = "${var.project}-agent-policy"
  description = "Shared policy for orchestrator and worker agents"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.*",
        ]
      },
      {
        Sid    = "AgentCoreRuntime"
        Effect = "Allow"
        Action = ["bedrock-agentcore:*"]
        Resource = ["*"]
      },
      {
        Sid    = "DynamoDBMemory"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
        ]
        Resource = [
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.project}-*",
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.project}-*/index/*",
        ]
      },
      {
        Sid    = "SecretsAccess"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project}/*",
        ]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = ["*"]
      },
      {
        Sid    = "SQSAccess"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = [var.queue_arn]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "orchestrator" {
  role       = aws_iam_role.orchestrator.name
  policy_arn = aws_iam_policy.agent_policy.arn
}

resource "aws_iam_role_policy_attachment" "worker" {
  role       = aws_iam_role.worker.name
  policy_arn = aws_iam_policy.agent_policy.arn
}

# -----------------------------------------------------
# CloudWatch Log Groups
# -----------------------------------------------------

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = "/${var.project}/orchestrator"
  retention_in_days = 30

  tags = { component = "runtime" }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/${var.project}/worker"
  retention_in_days = 30

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Secrets Manager — MCP credentials
# -----------------------------------------------------

resource "aws_secretsmanager_secret" "github_pat" {
  name        = "${var.project}/github-pat"
  description = "GitHub PAT for devai-bot machine user"

  tags = { component = "secrets" }
}

resource "aws_secretsmanager_secret" "figma_pat" {
  name        = "${var.project}/figma-pat"
  description = "Figma service account PAT"

  tags = { component = "secrets" }
}

resource "aws_secretsmanager_secret" "teams_credentials" {
  name        = "${var.project}/teams-credentials"
  description = "Microsoft Teams Azure AD app credentials"

  tags = { component = "secrets" }
}

# -----------------------------------------------------
# Webhook Task Definition
# -----------------------------------------------------

resource "aws_ecs_task_definition" "webhook" {
  family                   = "${var.project}-webhook"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256  # 0.25 vCPU
  memory                   = 512  # 0.5 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.orchestrator.arn

  container_definitions = jsonencode([{
    name      = "webhook"
    image     = "${var.webhook_image}:latest"
    essential = true

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "SQS_QUEUE_URL", value = var.queue_url },
      { name = "PROJECT", value = var.project },
    ]

    secrets = [
      {
        name      = "GITHUB_PAT"
        valueFrom = aws_secretsmanager_secret.github_pat.arn
      },
      {
        name      = "FIGMA_PAT"
        valueFrom = aws_secretsmanager_secret.figma_pat.arn
      },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.orchestrator.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "webhook"
      }
    }
  }])

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Webhook ECS Service
# -----------------------------------------------------

resource "aws_ecs_service" "webhook" {
  name            = "${var.project}-webhook"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.webhook.arn
  desired_count   = var.webhook_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.webhook_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "webhook"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Worker Task Definition
# -----------------------------------------------------

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.worker.arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${var.worker_image}:latest"
    essential = true
    stopTimeout = 120

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "SQS_QUEUE_URL", value = var.queue_url },
      { name = "PROJECT", value = var.project },
    ]

    secrets = [
      {
        name      = "GITHUB_PAT"
        valueFrom = aws_secretsmanager_secret.github_pat.arn
      },
      {
        name      = "FIGMA_PAT"
        valueFrom = aws_secretsmanager_secret.figma_pat.arn
      },
      {
        name      = "TEAMS_CREDENTIALS"
        valueFrom = aws_secretsmanager_secret.teams_credentials.arn
      },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Worker ECS Service (Fargate Spot, SQS-driven)
# -----------------------------------------------------

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 0 # Scale-to-zero; SQS auto-scaling drives task count

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.worker_security_group_id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Auto-Scaling — Webhook
# -----------------------------------------------------

resource "aws_appautoscaling_target" "webhook" {
  max_capacity       = var.environment == "production" ? 4 : 2
  min_capacity       = var.webhook_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.webhook.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "webhook_cpu" {
  name               = "${var.project}-webhook-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.webhook.resource_id
  scalable_dimension = aws_appautoscaling_target.webhook.scalable_dimension
  service_namespace  = aws_appautoscaling_target.webhook.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70.0
  }
}

# -----------------------------------------------------
# Auto-Scaling — Worker (SQS-based step scaling)
# -----------------------------------------------------

resource "aws_appautoscaling_target" "worker" {
  max_capacity       = var.environment == "production" ? 5 : 3
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "worker_sqs" {
  name               = "${var.project}-worker-sqs-scaling"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker.service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_lower_bound = 0
      metric_interval_upper_bound = 1
      scaling_adjustment          = 1
    }

    step_adjustment {
      metric_interval_lower_bound = 1
      metric_interval_upper_bound = 5
      scaling_adjustment          = 3
    }

    step_adjustment {
      metric_interval_lower_bound = 5
      scaling_adjustment          = 5
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_sqs_depth" {
  alarm_name          = "${var.project}-worker-sqs-depth"
  alarm_description   = "Scale workers based on SQS queue depth"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.queue_name
  }

  alarm_actions = [aws_appautoscaling_policy.worker_sqs.arn]

  tags = { component = "runtime" }
}
