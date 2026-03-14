# DynamoDB tables for the Mason memory subsystem

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
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }

  deletion_protection_enabled = var.environment == "production"

  global_secondary_index {
    name            = "agent_id-index"
    hash_key        = "agent_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  tags = {
    component = "memory"
  }
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

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }

  deletion_protection_enabled = var.environment == "production"

  global_secondary_index {
    name            = "task_id-index"
    hash_key        = "task_id"
    range_key       = "episode_id"
    projection_type = "ALL"
  }

  tags = {
    component = "memory"
  }
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

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }

  deletion_protection_enabled = var.environment == "production"

  tags = {
    component = "memory"
  }
}
