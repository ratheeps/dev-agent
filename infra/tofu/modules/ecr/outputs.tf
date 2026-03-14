output "webhook_repository_url" {
  description = "ECR repository URL for webhook image"
  value       = aws_ecr_repository.webhook.repository_url
}

output "worker_repository_url" {
  description = "ECR repository URL for worker image"
  value       = aws_ecr_repository.worker.repository_url
}

output "webhook_repository_arn" {
  description = "ECR repository ARN for webhook image"
  value       = aws_ecr_repository.webhook.arn
}

output "worker_repository_arn" {
  description = "ECR repository ARN for worker image"
  value       = aws_ecr_repository.worker.arn
}
