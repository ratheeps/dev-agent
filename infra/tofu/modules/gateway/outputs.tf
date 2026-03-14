output "alb_arn" {
  description = "ALB ARN"
  value       = aws_lb.main.arn
}

output "alb_dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID (for Route53 alias)"
  value       = aws_lb.main.zone_id
}

output "target_group_arn" {
  description = "Webhook target group ARN"
  value       = aws_lb_target_group.webhook.arn
}

output "certificate_arn" {
  description = "ACM certificate ARN (empty if no domain)"
  value       = local.certificate_arn
}

output "api_url" {
  description = "ALB URL for webhook endpoints"
  value       = local.certificate_arn != "" ? "https://${aws_lb.main.dns_name}" : "http://${aws_lb.main.dns_name}"
}

output "webhook_endpoint" {
  description = "Full webhook endpoint URL"
  value       = local.certificate_arn != "" ? "https://${aws_lb.main.dns_name}/webhooks/teams/message" : "http://${aws_lb.main.dns_name}/webhooks/teams/message"
}
