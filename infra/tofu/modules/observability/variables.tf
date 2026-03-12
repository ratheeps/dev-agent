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
