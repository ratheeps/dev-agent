variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (staging or production)"
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "Environment must be 'staging' or 'production'."
  }
}

variable "project" {
  description = "Project name used for tagging and naming"
  type        = string
  default     = "mason"
}

variable "daily_cost_alarm_threshold" {
  description = "Bedrock invocation count threshold for daily cost alarm"
  type        = number
  default     = 10000
}

variable "alert_email" {
  description = "Email address for SNS alarm notifications (optional)"
  type        = string
  default     = ""
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "webhook_desired_count" {
  description = "Desired number of webhook ECS tasks"
  type        = number
  default     = 1
}

variable "worker_cpu" {
  description = "Worker task CPU units (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "Worker task memory in MiB"
  type        = number
  default     = 2048
}

variable "domain_name" {
  description = "Custom domain name for the ALB (optional)"
  type        = string
  default     = ""
}

variable "hosted_zone_id" {
  description = "Route53 hosted zone ID (required if domain_name is set)"
  type        = string
  default     = ""
}

variable "github_repo" {
  description = "GitHub repository for CI/CD (owner/repo format)"
  type        = string
  default     = "giftbee/mason"
}

variable "state_bucket" {
  description = "S3 bucket for OpenTofu state"
  type        = string
  default     = "giftbee-tofu-state"
}

variable "lock_table" {
  description = "DynamoDB table for OpenTofu state locking"
  type        = string
  default     = "giftbee-tofu-locks"
}
