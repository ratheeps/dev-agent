variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "kms_key_arn" {
  description = "KMS key ARN for server-side encryption (empty = AWS-managed)"
  type        = string
  default     = ""
}
