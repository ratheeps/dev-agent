# GitHub Actions OIDC provider and IAM role for CI/CD

data "aws_caller_identity" "current" {}

# -----------------------------------------------------
# GitHub OIDC Provider
# -----------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = { component = "cicd" }
}

# -----------------------------------------------------
# GitHub Actions IAM Role
# -----------------------------------------------------

resource "aws_iam_role" "github_actions" {
  name        = "${var.project}-github-actions"
  description = "Role assumed by GitHub Actions for ECR push, ECS deploy, and OpenTofu"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/${var.deploy_branch}"
        }
      }
    }]
  })

  tags = { component = "cicd" }
}

# ECR push permissions
resource "aws_iam_policy" "ecr_push" {
  name        = "${var.project}-ecr-push"
  description = "Push container images to ECR"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
        ]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = var.ecr_repository_arns
      },
    ]
  })
}

# ECS deploy permissions
resource "aws_iam_policy" "ecs_deploy" {
  name        = "${var.project}-ecs-deploy"
  description = "Update ECS services and task definitions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:DeregisterTaskDefinition",
          "ecs:ListTasks",
          "ecs:DescribeTasks",
        ]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = var.ecs_role_arns
      },
    ]
  })
}

# OpenTofu state permissions
resource "aws_iam_policy" "tofu_state" {
  name        = "${var.project}-tofu-state"
  description = "Read/write OpenTofu state in S3 and DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.state_bucket}",
          "arn:aws:s3:::${var.state_bucket}/mason/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = [
          "arn:aws:dynamodb:*:${data.aws_caller_identity.current.account_id}:table/${var.lock_table}",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecr_push" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.ecr_push.arn
}

resource "aws_iam_role_policy_attachment" "ecs_deploy" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.ecs_deploy.arn
}

resource "aws_iam_role_policy_attachment" "tofu_state" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.tofu_state.arn
}
