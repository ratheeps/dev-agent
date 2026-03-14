output "waf_web_acl_arn" {
  description = "WAF Web ACL ARN"
  value       = aws_wafv2_web_acl.main.arn
}

output "kms_key_arn" {
  description = "KMS key ARN (production only, empty in staging)"
  value       = length(aws_kms_key.main) > 0 ? aws_kms_key.main[0].arn : ""
}

output "atlassian_credentials_secret_arn" {
  description = "Atlassian credentials secret ARN"
  value       = aws_secretsmanager_secret.atlassian_credentials.arn
}

output "anthropic_api_key_secret_arn" {
  description = "Anthropic API key secret ARN"
  value       = aws_secretsmanager_secret.anthropic_api_key.arn
}
