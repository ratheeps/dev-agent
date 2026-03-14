variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "github_repo" {
  description = "GitHub repository (owner/repo format)"
  type        = string
}

variable "deploy_branch" {
  description = "Branch allowed to deploy"
  type        = string
  default     = "main"
}

variable "ecr_repository_arns" {
  description = "ECR repository ARNs for push permissions"
  type        = list(string)
}

variable "ecs_role_arns" {
  description = "ECS role ARNs for iam:PassRole"
  type        = list(string)
}

variable "state_bucket" {
  description = "S3 bucket for OpenTofu state"
  type        = string
}

variable "lock_table" {
  description = "DynamoDB table for OpenTofu state locking"
  type        = string
}
