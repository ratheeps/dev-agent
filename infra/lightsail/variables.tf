variable "project" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "mason"
}

variable "environment" {
  description = "Deployment environment (staging, production)"
  type        = string
  default     = "staging"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# -----------------------------------------------------
# Lightsail Instance
# -----------------------------------------------------

variable "instance_blueprint" {
  description = "Lightsail instance OS blueprint"
  type        = string
  default     = "amazon_linux_2023"
}

variable "instance_bundle" {
  description = "Lightsail instance size (nano=$3.50, micro=$5, small=$10, medium=$20)"
  type        = string
  default     = "small_3_0" # 2GB RAM, 1 vCPU — $10/mo
}

variable "ssh_key_name" {
  description = "Name of the Lightsail SSH key pair"
  type        = string
}

# -----------------------------------------------------
# Alerts
# -----------------------------------------------------

variable "alert_email" {
  description = "Email for alarm notifications (empty = no subscription)"
  type        = string
  default     = ""
}
