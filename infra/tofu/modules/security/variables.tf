variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "alb_arn" {
  description = "ALB ARN to attach WAF to"
  type        = string
}
