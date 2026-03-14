output "orchestrator_role_arn" {
  value = aws_iam_role.orchestrator.arn
}

output "orchestrator_role_name" {
  value = aws_iam_role.orchestrator.name
}

output "worker_role_arn" {
  value = aws_iam_role.worker.arn
}

output "worker_role_name" {
  value = aws_iam_role.worker.name
}

output "orchestrator_log_group" {
  value = aws_cloudwatch_log_group.orchestrator.name
}

output "worker_log_group" {
  value = aws_cloudwatch_log_group.worker.name
}

output "github_pat_secret_arn" {
  value = aws_secretsmanager_secret.github_pat.arn
}

output "figma_pat_secret_arn" {
  value = aws_secretsmanager_secret.figma_pat.arn
}

output "teams_credentials_secret_arn" {
  value = aws_secretsmanager_secret.teams_credentials.arn
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "webhook_service_name" {
  description = "Webhook ECS service name"
  value       = aws_ecs_service.webhook.name
}

output "worker_service_name" {
  description = "Worker ECS service name"
  value       = aws_ecs_service.worker.name
}
