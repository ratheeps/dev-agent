output "domain_name" {
  description = "Route53 record domain name"
  value       = length(aws_route53_record.main) > 0 ? aws_route53_record.main[0].fqdn : ""
}
