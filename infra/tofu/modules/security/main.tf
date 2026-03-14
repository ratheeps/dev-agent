# WAFv2, KMS key, and additional secrets for production hardening

data "aws_caller_identity" "current" {}

# -----------------------------------------------------
# WAFv2 Web ACL — attached to ALB
# -----------------------------------------------------

resource "aws_wafv2_web_acl" "main" {
  name        = "${var.project}-waf"
  description = "WAF rules for Mason ALB"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # AWS Managed Rules — Common Rule Set
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-common-rules"
      sampled_requests_enabled   = true
    }
  }

  # AWS Managed Rules — Known Bad Inputs
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # Rate-based rule — 100 requests per 5 minutes per IP
  rule {
    name     = "RateLimit"
    priority = 3

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 100
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project}-waf"
    sampled_requests_enabled   = true
  }

  tags = { component = "security" }
}

# Attach WAF to ALB
resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

# WAF logging to CloudWatch
resource "aws_wafv2_web_acl_logging_configuration" "main" {
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  resource_arn            = aws_wafv2_web_acl.main.arn
}

resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${var.project}"
  retention_in_days = 30

  tags = { component = "security" }
}

# -----------------------------------------------------
# Additional Secrets
# -----------------------------------------------------

resource "aws_secretsmanager_secret" "atlassian_credentials" {
  name        = "${var.project}/atlassian-credentials"
  description = "Atlassian Jira/Confluence API credentials"

  tags = { component = "secrets" }
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "${var.project}/anthropic-api-key"
  description = "Anthropic API key for Claude models"

  tags = { component = "secrets" }
}

# -----------------------------------------------------
# KMS Key (production only)
# -----------------------------------------------------

resource "aws_kms_key" "main" {
  count                   = var.environment == "production" ? 1 : 0
  description             = "Mason encryption key for DynamoDB, SQS, Secrets, Logs"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RootAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Principal = {
          Service = "logs.amazonaws.com"
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
      },
    ]
  })

  tags = { component = "security" }
}

resource "aws_kms_alias" "main" {
  count         = var.environment == "production" ? 1 : 0
  name          = "alias/${var.project}"
  target_key_id = aws_kms_key.main[0].key_id
}
