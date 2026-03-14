variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "daily_cost_alarm_threshold" {
  type    = number
  default = 10000
}

variable "alert_email" {
  type    = string
  default = ""
}

variable "memory_table_names" {
  description = "List of DynamoDB memory table names for dashboard widgets"
  type        = list(string)
}

variable "ecs_cluster_name" {
  description = "ECS cluster name for dashboard metrics"
  type        = string
}

variable "webhook_service_name" {
  description = "Webhook ECS service name for dashboard metrics"
  type        = string
}

variable "worker_service_name" {
  description = "Worker ECS service name for dashboard metrics"
  type        = string
}

variable "queue_name" {
  description = "SQS queue name for dashboard metrics"
  type        = string
}

variable "dlq_name" {
  description = "SQS DLQ name for alarm"
  type        = string
}

variable "alb_arn_suffix" {
  description = "ALB ARN suffix for CloudWatch dimensions"
  type        = string
}

variable "target_group_arn_suffix" {
  description = "Target group ARN suffix for CloudWatch dimensions"
  type        = string
}
