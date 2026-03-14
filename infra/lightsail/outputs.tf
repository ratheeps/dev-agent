output "instance_name" {
  description = "Lightsail instance name"
  value       = aws_lightsail_instance.mason.name
}

output "static_ip" {
  description = "Public static IP address"
  value       = aws_lightsail_static_ip.mason.ip_address
}

output "sqs_queue_url" {
  description = "SQS task queue URL"
  value       = aws_sqs_queue.tasks.url
}

output "sqs_dlq_url" {
  description = "SQS dead-letter queue URL"
  value       = aws_sqs_queue.tasks_dlq.url
}

output "session_table" {
  description = "DynamoDB session memory table name"
  value       = aws_dynamodb_table.session_memory.name
}

output "episodic_table" {
  description = "DynamoDB episodic memory table name"
  value       = aws_dynamodb_table.episodic_memory.name
}

output "semantic_table" {
  description = "DynamoDB semantic memory table name"
  value       = aws_dynamodb_table.semantic_memory.name
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/${var.ssh_key_name}.pem ec2-user@${aws_lightsail_static_ip.mason.ip_address}"
}
