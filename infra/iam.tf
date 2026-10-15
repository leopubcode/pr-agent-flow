# --- Lambda execution role: can only send to the main queue ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.project_name}-webhook-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_sqs_send" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.main.arn]
  }
}

resource "aws_iam_role_policy" "lambda_sqs_send" {
  name   = "${var.project_name}-lambda-sqs-send"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_sqs_send.json
}

# --- Consumer identity: static IAM user credentials for the operator's
# own host (not running inside AWS, so no role to assume). Scoped to
# exactly the receive/delete/change-visibility it needs on the main
# queue only -- no DLQ access, that's for human/ops inspection.
#
# Tradeoff: long-lived static keys are the weakest link in this design.
# Acceptable for a single-operator tool; rotate periodically
# (`terraform taint aws_iam_access_key.consumer` + apply) and consider
# migrating to short-lived credentials (e.g. `aws sso login`) if this
# grows beyond single-operator use. ---

resource "aws_iam_user" "consumer" {
  name = "${var.project_name}-consumer"
}

resource "aws_iam_access_key" "consumer" {
  user = aws_iam_user.consumer.name
}

data "aws_iam_policy_document" "consumer_sqs" {
  statement {
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.main.arn]
  }
}

resource "aws_iam_user_policy" "consumer_sqs" {
  name   = "${var.project_name}-consumer-sqs"
  user   = aws_iam_user.consumer.name
  policy = data.aws_iam_policy_document.consumer_sqs.json
}
