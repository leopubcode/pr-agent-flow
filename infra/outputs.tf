output "webhook_endpoint" {
  description = "URL to configure as the GitHub webhook's Payload URL"
  value       = "${aws_apigatewayv2_stage.default.invoke_url}webhook"
}

output "sqs_queue_url" {
  value = aws_sqs_queue.main.url
}

output "sqs_queue_arn" {
  value = aws_sqs_queue.main.arn
}

output "sqs_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "consumer_access_key_id" {
  value     = aws_iam_access_key.consumer.id
  sensitive = true
}

output "consumer_secret_access_key" {
  value     = aws_iam_access_key.consumer.secret
  sensitive = true
}
