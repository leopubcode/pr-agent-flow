"""GitHub webhook receiver.

Verifies the GitHub HMAC signature, filters for PR comment/review/close
events, normalizes them into a small schema, and forwards them to SQS.

Deliberately stdlib + boto3 only (both available in the Lambda Python
runtime) so Terraform can zip this directory with no build/install step.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

SCHEMA_VERSION = 1

_sqs = None


def _sqs_client():
    # Created lazily (rather than at import time) so this module can be
    # imported for unit tests without AWS credentials/region configured --
    # the Lambda runtime always has a region set, so this is a no-op there.
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs")
    return _sqs


def verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _pr_ref(payload: dict[str, Any], key: str) -> str | None:
    pr = payload.get("pull_request")
    if not pr:
        return None
    return pr.get(key, {}).get("ref")


def normalize(gh_event: str, action: str | None, payload: dict[str, Any], delivery_id: str) -> dict[str, Any] | None:
    """Return a normalized message dict, or None if this event should be ignored."""
    received_at = datetime.now(timezone.utc).isoformat()

    base = {
        "schema_version": SCHEMA_VERSION,
        "delivery_id": delivery_id,
        "received_at": received_at,
    }

    if gh_event == "issue_comment" and action == "created" and payload.get("issue", {}).get("pull_request"):
        repo = payload["repository"]
        comment = payload["comment"]
        return {
            **base,
            "event_type": "issue_comment",
            "repo_full_name": repo["full_name"],
            "pr_number": payload["issue"]["number"],
            # issue_comment payloads don't carry the head ref directly; the
            # consumer resolves it lazily via the GitHub API.
            "branch": None,
            "base_branch": None,
            "is_merged": False,
            "actor": comment["user"]["login"],
            "body": comment["body"],
            "html_url": comment["html_url"],
            "file_path": None,
            "line": None,
            "diff_hunk": None,
        }

    if gh_event == "pull_request_review" and action == "submitted":
        repo = payload["repository"]
        review = payload["review"]
        return {
            **base,
            "event_type": "pull_request_review",
            "repo_full_name": repo["full_name"],
            "pr_number": payload["pull_request"]["number"],
            "branch": _pr_ref(payload, "head"),
            "base_branch": _pr_ref(payload, "base"),
            "is_merged": False,
            "actor": review["user"]["login"],
            "body": review.get("body") or "",
            "html_url": review["html_url"],
            "file_path": None,
            "line": None,
            "diff_hunk": None,
        }

    if gh_event == "pull_request_review_comment" and action == "created":
        repo = payload["repository"]
        comment = payload["comment"]
        return {
            **base,
            "event_type": "pull_request_review_comment",
            "repo_full_name": repo["full_name"],
            "pr_number": payload["pull_request"]["number"],
            "branch": _pr_ref(payload, "head"),
            "base_branch": _pr_ref(payload, "base"),
            "is_merged": False,
            "actor": comment["user"]["login"],
            "body": comment["body"],
            "html_url": comment["html_url"],
            "file_path": comment.get("path"),
            "line": comment.get("line"),
            "diff_hunk": comment.get("diff_hunk"),
        }

    if gh_event == "pull_request" and action == "closed":
        repo = payload["repository"]
        pr = payload["pull_request"]
        return {
            **base,
            "event_type": "pull_request",
            "repo_full_name": repo["full_name"],
            "pr_number": pr["number"],
            "branch": pr["head"]["ref"],
            "base_branch": pr["base"]["ref"],
            "is_merged": bool(pr.get("merged")),
            "actor": payload["sender"]["login"],
            "body": "",
            "html_url": pr["html_url"],
            "file_path": None,
            "line": None,
            "diff_hunk": None,
        }

    return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    raw_body = base64.b64decode(event["body"]) if event.get("isBase64Encoded") else (event.get("body") or "").encode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    secret = os.environ["GITHUB_WEBHOOK_SECRET"]
    if not verify_signature(raw_body, headers.get("x-hub-signature-256"), secret):
        return {"statusCode": 401, "body": "invalid signature"}

    gh_event = headers.get("x-github-event")
    delivery_id = headers.get("x-github-delivery", "")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "invalid json"}

    action = payload.get("action")
    msg = normalize(gh_event, action, payload, delivery_id)
    if msg is None:
        return {"statusCode": 200, "body": "ignored"}

    _sqs_client().send_message(QueueUrl=os.environ["SQS_QUEUE_URL"], MessageBody=json.dumps(msg))
    return {"statusCode": 200, "body": "queued"}
