output "session_table_name" {
  description = "DynamoDB session memory table name"
  value       = module.memory.session_table_name
}

output "episodic_table_name" {
  description = "DynamoDB episodic memory table name"
  value       = module.memory.episodic_table_name
}

output "semantic_table_name" {
  description = "DynamoDB semantic memory table name"
  value       = module.memory.semantic_table_name
}

output "orchestrator_role_arn" {
  description = "IAM role ARN for the orchestrator agent"
  value       = module.runtime.orchestrator_role_arn
}

output "worker_role_arn" {
  description = "IAM role ARN for worker agents"
  value       = module.runtime.worker_role_arn
}

output "webhook_api_url" {
  description = "ALB URL for webhook endpoints"
  value       = module.gateway.api_url
}

output "alert_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = module.observability.alert_topic_arn
}

output "alb_dns_name" {
  description = "ALB DNS name"
  value       = module.gateway.alb_dns_name
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.runtime.ecs_cluster_name
}

output "queue_url" {
  description = "SQS task queue URL"
  value       = module.queue.queue_url
}

output "webhook_ecr_url" {
  description = "ECR repository URL for webhook image"
  value       = module.ecr.webhook_repository_url
}

output "worker_ecr_url" {
  description = "ECR repository URL for worker image"
  value       = module.ecr.worker_repository_url
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions"
  value       = module.cicd.github_actions_role_arn
}
