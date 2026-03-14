variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "webhook_image" {
  description = "ECR image URI for the webhook container (without tag)"
  type        = string
}

variable "worker_image" {
  description = "ECR image URI for the worker container (without tag)"
  type        = string
}

variable "webhook_desired_count" {
  description = "Desired number of webhook tasks"
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

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "webhook_security_group_id" {
  description = "Security group ID for webhook ECS tasks"
  type        = string
}

variable "worker_security_group_id" {
  description = "Security group ID for worker ECS tasks"
  type        = string
}

variable "target_group_arn" {
  description = "ALB target group ARN for the webhook service"
  type        = string
}

variable "queue_url" {
  description = "SQS task queue URL"
  type        = string
}

variable "queue_arn" {
  description = "SQS task queue ARN"
  type        = string
}

variable "queue_name" {
  description = "SQS task queue name"
  type        = string
}
