# The webhook handler is stdlib + boto3 only (boto3 ships with the Lambda
# Python runtime), so we can zip the directory directly with no pip
# install / build step.
data "archive_file" "webhook" {
  type        = "zip"
  source_dir  = "${path.module}/../webhook"
  output_path = "${path.module}/.build/webhook.zip"
  excludes    = ["tests"]
}

resource "aws_lambda_function" "webhook" {
  function_name    = "${var.project_name}-webhook"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 10
  filename         = data.archive_file.webhook.output_path
  source_code_hash = data.archive_file.webhook.output_base64sha256

  environment {
    variables = {
      GITHUB_WEBHOOK_SECRET = var.github_webhook_secret
      SQS_QUEUE_URL          = aws_sqs_queue.main.url
    }
  }
}
