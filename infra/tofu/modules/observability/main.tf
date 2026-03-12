# CloudWatch dashboards and alarms for Dev-AI

# -----------------------------------------------------
# SNS Alert Topic
# -----------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name         = "${var.project}-alerts"
  display_name = "Dev-AI Alerts"

  tags = { component = "observability" }
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# -----------------------------------------------------
# CloudWatch Dashboard
# -----------------------------------------------------

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${var.project}-operations"

  dashboard_body = jsonencode({
    widgets = concat(
      # DynamoDB capacity widgets for each memory table
      [for table_name in var.memory_table_names : {
        type   = "metric"
        x      = 0
        y      = index(var.memory_table_names, table_name) * 6
        width  = 12
        height = 6
        properties = {
          title   = "${table_name} Read/Write Capacity"
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", table_name],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", table_name],
          ]
          period = 300
          stat   = "Sum"
          region = data.aws_region.current.name
        }
      }],
      # Bedrock invocation widget
      [{
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Bedrock Model Invocations"
          metrics = [
            ["AWS/Bedrock", "InvocationCount"],
          ]
          period = 300
          stat   = "Sum"
          region = data.aws_region.current.name
        }
      }],
    )
  })
}

data "aws_region" "current" {}

# -----------------------------------------------------
# Cost Alarm — daily Bedrock invocation threshold
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "daily_cost" {
  alarm_name          = "${var.project}-daily-cost-alarm"
  alarm_description   = "Dev-AI daily Bedrock cost exceeds threshold"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "InvocationCount"
  namespace           = "AWS/Bedrock"
  period              = 86400 # 24 hours
  statistic           = "Sum"
  threshold           = var.daily_cost_alarm_threshold
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}

# -----------------------------------------------------
# Error Rate Alarm — pipeline failures
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "error_rate" {
  alarm_name          = "${var.project}-error-rate-alarm"
  alarm_description   = "Dev-AI pipeline error rate exceeds threshold"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "PipelineErrors"
  namespace           = "DevAI"
  period              = 3600 # 1 hour
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}
