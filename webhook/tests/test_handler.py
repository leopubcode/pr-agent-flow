import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import handler  # noqa: E402


SECRET = "test-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_valid():
    body = b'{"a": 1}'
    assert handler.verify_signature(body, sign(body), SECRET) is True


def test_verify_signature_invalid():
    body = b'{"a": 1}'
    assert handler.verify_signature(body, "sha256=deadbeef", SECRET) is False


def test_verify_signature_missing():
    body = b'{"a": 1}'
    assert handler.verify_signature(body, None, SECRET) is False
    assert handler.verify_signature(body, "", SECRET) is False
    assert handler.verify_signature(body, "not-sha256=abc", SECRET) is False


def test_normalize_issue_comment_on_pr():
    payload = {
        "repository": {"full_name": "org/repo"},
        "issue": {"number": 42, "pull_request": {"url": "https://api.github.com/..."}},
        "comment": {
            "user": {"login": "octocat"},
            "body": "please rename this",
            "html_url": "https://github.com/org/repo/pull/42#issuecomment-1",
        },
    }
    msg = handler.normalize("issue_comment", "created", payload, "delivery-1")
    assert msg is not None
    assert msg["event_type"] == "issue_comment"
    assert msg["pr_number"] == 42
    assert msg["branch"] is None
    assert msg["body"] == "please rename this"


def test_normalize_issue_comment_on_plain_issue_ignored():
    payload = {
        "repository": {"full_name": "org/repo"},
        "issue": {"number": 42},
        "comment": {"user": {"login": "octocat"}, "body": "hi", "html_url": "x"},
    }
    assert handler.normalize("issue_comment", "created", payload, "delivery-1") is None


def test_normalize_pull_request_review_submitted():
    payload = {
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 7,
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
        },
        "review": {"user": {"login": "reviewer"}, "body": "lgtm with nits", "html_url": "x"},
    }
    msg = handler.normalize("pull_request_review", "submitted", payload, "delivery-2")
    assert msg["event_type"] == "pull_request_review"
    assert msg["body"] == "lgtm with nits"
    assert msg["branch"] == "feature/x"
    assert msg["base_branch"] == "main"


def _review_payload(review_body, state="commented"):
    return {
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 7,
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
        },
        "review": {"user": {"login": "reviewer"}, "body": review_body, "state": state, "html_url": "x"},
    }


def test_normalize_pull_request_review_with_empty_body_ignored():
    payload = _review_payload("")
    assert handler.normalize("pull_request_review", "submitted", payload, "delivery-2") is None


def test_normalize_bodiless_approval_ignored():
    payload = _review_payload(None, state="approved")
    assert handler.normalize("pull_request_review", "submitted", payload, "delivery-2") is None


def test_normalize_pull_request_review_with_whitespace_body_ignored():
    payload = _review_payload("  \n\t ")
    assert handler.normalize("pull_request_review", "submitted", payload, "delivery-2") is None


def test_normalize_pull_request_review_comment_created():
    payload = {
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 7,
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
        },
        "comment": {
            "user": {"login": "reviewer"},
            "body": "fix this line",
            "html_url": "x",
            "path": "src/app.py",
            "line": 42,
            "diff_hunk": "@@ -1,2 +1,2 @@",
        },
    }
    msg = handler.normalize("pull_request_review_comment", "created", payload, "delivery-3")
    assert msg["file_path"] == "src/app.py"
    assert msg["line"] == 42


def test_normalize_pull_request_closed_merged():
    payload = {
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 7,
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            "merged": True,
            "html_url": "x",
        },
        "sender": {"login": "octocat"},
    }
    msg = handler.normalize("pull_request", "closed", payload, "delivery-4")
    assert msg["event_type"] == "pull_request"
    assert msg["is_merged"] is True


def test_normalize_irrelevant_event_ignored():
    assert handler.normalize("push", None, {}, "delivery-5") is None
    assert handler.normalize("pull_request", "opened", {"pull_request": {}}, "delivery-6") is None


def test_lambda_handler_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example/queue")
    event = {
        "body": json.dumps({"action": "created"}),
        "isBase64Encoded": False,
        "headers": {
            "x-hub-signature-256": "sha256=bad",
            "x-github-event": "issue_comment",
            "x-github-delivery": "d1",
        },
    }
    result = handler.lambda_handler(event, None)
    assert result["statusCode"] == 401
