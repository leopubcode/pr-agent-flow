variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used for all resource names"
  type        = string
  default     = "pr-agent-flow"
}

variable "github_webhook_secret" {
  description = "Shared secret configured on the GitHub webhook, used to verify X-Hub-Signature-256"
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub user or organization that owns the repositories"
  type        = string
}

variable "github_repositories" {
  description = "Repository names (without owner) to install the PR webhook on"
  type        = set(string)
}

variable "dlq_max_receive_count" {
  description = "Number of delivery attempts before a message is moved to the DLQ"
  type        = number
  default     = 5
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default     = {}
}
