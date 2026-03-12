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
  description = "API Gateway URL for Jira webhooks"
  value       = module.gateway.api_url
}

output "alert_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = module.observability.alert_topic_arn
}
