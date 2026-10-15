resource "github_repository_webhook" "pr_events" {
  for_each   = var.github_repositories
  repository = each.value
  active     = true

  events = [
    "issue_comment",
    "pull_request_review",
    "pull_request_review_comment",
    "pull_request",
  ]

  configuration {
    url          = "${aws_apigatewayv2_stage.default.invoke_url}webhook"
    content_type = "json"
    secret       = var.github_webhook_secret
    insecure_ssl = false
  }
}
