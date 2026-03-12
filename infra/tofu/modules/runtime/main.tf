# IAM roles, log groups, and secrets for Bedrock AgentCore Runtime

data "aws_caller_identity" "current" {}

# -----------------------------------------------------
# IAM Roles
# -----------------------------------------------------

resource "aws_iam_role" "orchestrator" {
  name        = "${var.project}-orchestrator-role"
  description = "Execution role for the Dev-AI Opus orchestrator agent"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { component = "runtime" }
}

resource "aws_iam_role" "worker" {
  name        = "${var.project}-worker-role"
  description = "Execution role for Dev-AI Sonnet worker agents"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { component = "runtime" }
}

# -----------------------------------------------------
# Shared IAM Policy
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
