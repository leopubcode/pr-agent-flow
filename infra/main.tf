# Local backend for v1 (single operator). Move to an S3 backend with
# state locking if this ever grows beyond one person applying changes.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}
