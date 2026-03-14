variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "domain_name" {
  description = "Custom domain name (empty = skip DNS setup)"
  type        = string
  default     = ""
}

variable "hosted_zone_id" {
  description = "Route53 hosted zone ID"
  type        = string
  default     = ""
}

variable "alb_dns_name" {
  description = "ALB DNS name for alias record"
  type        = string
}

variable "alb_zone_id" {
  description = "ALB hosted zone ID for alias record"
  type        = string
}
