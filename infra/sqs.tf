# Standard (non-FIFO) queue: dedup is handled by the consumer using the
# GitHub delivery ID, since FIFO's 5-minute dedup window is too short for
# GitHub's webhook retry window (up to ~1 hour).
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project_name}-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "main" {
  name                       = "${var.project_name}-events"
  visibility_timeout_seconds = 300 # headroom for first-time sandbox provisioning
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount      = var.dlq_max_receive_count
  })
}
