# DynamoDB tables for the Dev-AI memory subsystem

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

  ttl {
    attribute_name = "ttl"
    enabled        = true
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

  tags = {
    component = "memory"
  }
}
