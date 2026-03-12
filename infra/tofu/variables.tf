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
  default     = "dev-ai"
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
