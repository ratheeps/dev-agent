output "queue_url" {
  description = "SQS task queue URL"
  value       = aws_sqs_queue.tasks.url
}

output "queue_arn" {
  description = "SQS task queue ARN"
  value       = aws_sqs_queue.tasks.arn
}

output "queue_name" {
  description = "SQS task queue name"
  value       = aws_sqs_queue.tasks.name
}

output "dlq_url" {
  description = "SQS dead-letter queue URL"
  value       = aws_sqs_queue.tasks_dlq.url
}

output "dlq_arn" {
  description = "SQS dead-letter queue ARN"
  value       = aws_sqs_queue.tasks_dlq.arn
}

output "dlq_name" {
  description = "SQS dead-letter queue name"
  value       = aws_sqs_queue.tasks_dlq.name
}
