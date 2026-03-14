# SQS task queue with dead-letter queue for agent workers

resource "aws_sqs_queue" "tasks_dlq" {
  name                      = "${var.project}-tasks-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true

  tags = { component = "queue" }
}

resource "aws_sqs_queue" "tasks" {
  name                       = "${var.project}-tasks"
  visibility_timeout_seconds = 28800 # 8 hours — matches max worker runtime
  message_retention_seconds  = 1209600 # 14 days
  receive_wait_time_seconds  = 20 # long polling
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.tasks_dlq.arn
    maxReceiveCount     = 2
  })

  tags = { component = "queue" }
}

# Allow the DLQ to receive messages from the main queue
resource "aws_sqs_queue_redrive_allow_policy" "tasks_dlq" {
  queue_url = aws_sqs_queue.tasks_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.tasks.arn]
  })
}
