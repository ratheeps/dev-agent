output "session_table_name" {
  value = aws_dynamodb_table.session_memory.name
}

output "session_table_arn" {
  value = aws_dynamodb_table.session_memory.arn
}

output "episodic_table_name" {
  value = aws_dynamodb_table.episodic_memory.name
}

output "episodic_table_arn" {
  value = aws_dynamodb_table.episodic_memory.arn
}

output "semantic_table_name" {
  value = aws_dynamodb_table.semantic_memory.name
}

output "semantic_table_arn" {
  value = aws_dynamodb_table.semantic_memory.arn
}

output "table_names" {
  description = "List of all memory table names"
  value = [
    aws_dynamodb_table.session_memory.name,
    aws_dynamodb_table.episodic_memory.name,
    aws_dynamodb_table.semantic_memory.name,
  ]
}

output "table_arns" {
  description = "List of all memory table ARNs"
  value = [
    aws_dynamodb_table.session_memory.arn,
    aws_dynamodb_table.episodic_memory.arn,
    aws_dynamodb_table.semantic_memory.arn,
  ]
}
