# Local backend for v1 (single operator). Move to an S3 backend with
# state locking if this ever grows beyond one person applying changes.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# Token is read from the GITHUB_TOKEN env var so it never lands in tfvars.
# Needs admin rights on each repo in var.github_repositories (fine-grained
# PAT: "Webhooks: read and write").
provider "github" {
  owner = var.github_owner
}
