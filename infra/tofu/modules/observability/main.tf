# CloudWatch dashboards, alarms, and SNS for Mason

data "aws_region" "current" {}

# -----------------------------------------------------
# SNS Alert Topic
# -----------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name         = "${var.project}-alerts"
  display_name = "Mason Alerts"

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
      # DynamoDB capacity widgets
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
      # ECS CPU/Memory — Webhook
      [{
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          title   = "Webhook ECS CPU & Memory"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.webhook_service_name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.webhook_service_name],
          ]
          period = 300
          stat   = "Average"
          region = data.aws_region.current.name
        }
      }],
      # ECS CPU/Memory — Worker
      [{
        type   = "metric"
        x      = 12
        y      = 18
        width  = 12
        height = 6
        properties = {
          title   = "Worker ECS CPU & Memory"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.worker_service_name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.worker_service_name],
          ]
          period = 300
          stat   = "Average"
          region = data.aws_region.current.name
        }
      }],
      # SQS Metrics
      [{
        type   = "metric"
        x      = 0
        y      = 24
        width  = 12
        height = 6
        properties = {
          title   = "SQS Queue Depth & Age"
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.queue_name],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", var.queue_name],
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", var.queue_name],
          ]
          period = 300
          stat   = "Maximum"
          region = data.aws_region.current.name
        }
      }],
      # ALB Metrics
      [{
        type   = "metric"
        x      = 12
        y      = 24
        width  = 12
        height = 6
        properties = {
          title   = "ALB Request Count & Response Time"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix],
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", var.target_group_arn_suffix, "LoadBalancer", var.alb_arn_suffix],
          ]
          period = 300
          stat   = "Sum"
          region = data.aws_region.current.name
        }
      }],
    )
  })
}

# -----------------------------------------------------
# Cost Alarm — daily Bedrock invocation threshold
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "daily_cost" {
  alarm_name          = "${var.project}-daily-cost-alarm"
  alarm_description   = "Mason daily Bedrock cost exceeds threshold"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "InvocationCount"
  namespace           = "AWS/Bedrock"
  period              = 86400
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
  alarm_description   = "Mason pipeline error rate exceeds threshold"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "PipelineErrors"
  namespace           = "Mason"
  period              = 3600
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}

# -----------------------------------------------------
# DLQ Messages Alarm — failed tasks
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.project}-dlq-messages"
  alarm_description   = "Messages in DLQ — task processing failure"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.dlq_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}

# -----------------------------------------------------
# SQS Oldest Message Alarm — stuck tasks
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "sqs_oldest_message" {
  alarm_name          = "${var.project}-sqs-oldest-message"
  alarm_description   = "SQS oldest message > 1 hour — task may be stuck"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 3600
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.queue_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}

# -----------------------------------------------------
# ALB 5xx Alarm
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.project}-alb-5xx"
  alarm_description   = "ALB 5xx rate exceeds 5% over 5 minutes"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 5
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "error_rate"
    expression  = "(errors / requests) * 100"
    label       = "5xx Error Rate"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      metric_name = "HTTPCode_ELB_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      period      = 300
      stat        = "Sum"
      dimensions = {
        LoadBalancer = var.alb_arn_suffix
      }
    }
  }

  metric_query {
    id = "requests"
    metric {
      metric_name = "RequestCount"
      namespace   = "AWS/ApplicationELB"
      period      = 300
      stat        = "Sum"
      dimensions = {
        LoadBalancer = var.alb_arn_suffix
      }
    }
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}

# -----------------------------------------------------
# Webhook Healthy Hosts Alarm
# -----------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "webhook_healthy_hosts" {
  alarm_name          = "${var.project}-webhook-healthy-hosts"
  alarm_description   = "Webhook service has no healthy hosts"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  treat_missing_data  = "breaching"

  dimensions = {
    TargetGroup  = var.target_group_arn_suffix
    LoadBalancer = var.alb_arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = { component = "observability" }
}
