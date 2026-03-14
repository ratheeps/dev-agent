output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "alb_security_group_id" {
  description = "Security group ID for the ALB"
  value       = aws_security_group.alb.id
}

output "webhook_ecs_security_group_id" {
  description = "Security group ID for webhook ECS tasks"
  value       = aws_security_group.webhook_ecs.id
}

output "worker_ecs_security_group_id" {
  description = "Security group ID for worker ECS tasks"
  value       = aws_security_group.worker_ecs.id
}
