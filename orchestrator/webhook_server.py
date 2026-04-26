import hashlib
import hmac
import json
import logging
import os
import sys
import threading
from datetime import datetime

from flask import Flask, jsonify, request
from dotenv import load_dotenv

# Add scripts/ to path so we can import remediate_issue
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from run_remediation import remediate_issue

load_dotenv()

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
TARGET_REPO = "SeanDreifuss/superset"
SECURITY_LABEL = "security-finding"

app = Flask(__name__)

# ---------- Logging ----------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("webhook.log"),
    ],
)
log = logging.getLogger(__name__)


# ---------- State: simple in-memory dedup ----------
# Tracks issue numbers currently being processed
# Prevents duplicate webhook events from spawning duplicate sessions

processing = set()
processing_lock = threading.Lock()


# ---------- Signature verification ----------

def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify the webhook came from GitHub using HMAC-SHA256."""
    if not GITHUB_WEBHOOK_SECRET:
        log.warning("No GITHUB_WEBHOOK_SECRET set — skipping signature verification")
        return True
    if not signature_header:
        log.warning("No signature header in request")
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature_header, expected)


# ---------- Background worker ----------

def run_remediation_background(issue_number: int, issue_title: str):
    """
    Run the remediation pipeline in a background thread.
    GitHub webhooks time out at 10 seconds — we must return 200 immediately
    and do the actual work here.
    """
    log.info(f"[issue-{issue_number}] Starting remediation pipeline")
    try:
        result = remediate_issue(issue_number)
        status = result.get("status")
        pr_url = result.get("pr_url")

        if pr_url:
            log.info(f"[issue-{issue_number}] ✅ PR opened: {pr_url}")
        elif status == "escalated":
            log.info(f"[issue-{issue_number}] ⬆️  Escalated: {result.get('triage_reasoning', '')[:120]}")
        else:
            log.info(f"[issue-{issue_number}] ⚠️  Completed with status: {status}")

        log.info(f"[issue-{issue_number}] Full result: {json.dumps(result, indent=2)}")

    except Exception as e:
        log.error(f"[issue-{issue_number}] ❌ Pipeline error: {e}", exc_info=True)

    finally:
        with processing_lock:
            processing.discard(issue_number)
        log.info(f"[issue-{issue_number}] Pipeline complete. Slot released.")


# ---------- Webhook endpoint ----------

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """
    Receive GitHub issue events.
    Fires when an issue is opened or labeled.
    """
    # 1. Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, signature):
        log.warning("Webhook signature verification failed")
        return jsonify({"error": "Invalid signature"}), 401

    # 2. Parse payload
    event_type = request.headers.get("X-GitHub-Event", "")
    payload = request.json

    log.info(f"Received GitHub event: {event_type}")

    # 3. Only handle issue events
    if event_type != "issues":
        return jsonify({"skipped": f"event type '{event_type}' not handled"}), 200

    action = payload.get("action", "")
    issue = payload.get("issue", {})
    repo = payload.get("repository", {}).get("full_name", "")
    issue_number = issue.get("number")
    issue_title = issue.get("title", "")
    labels = [label["name"] for label in issue.get("labels", [])]

    log.info(f"Issue event: action={action} issue=#{issue_number} repo={repo} labels={labels}")

    # 4. Only handle opened or labeled actions
    if action not in ("opened", "labeled"):
        return jsonify({"skipped": f"action '{action}' not handled"}), 200

    # 5. Only handle the target repo
    if repo != TARGET_REPO:
        log.info(f"Skipping — repo {repo} is not {TARGET_REPO}")
        return jsonify({"skipped": "wrong repo"}), 200

    # 6. Only handle security findings
    if SECURITY_LABEL not in labels:
        log.info(f"Skipping issue #{issue_number} — no '{SECURITY_LABEL}' label")
        return jsonify({"skipped": "no security-finding label"}), 200

    # 7. Dedup — don't process the same issue twice concurrently
    with processing_lock:
        if issue_number in processing:
            log.info(f"Issue #{issue_number} already being processed — skipping duplicate")
            return jsonify({"skipped": "already processing"}), 200
        processing.add(issue_number)

    # 8. Spawn background thread — MUST return 200 before GitHub times out
    log.info(f"[issue-{issue_number}] Spawning remediation thread for: {issue_title}")
    thread = threading.Thread(
        target=run_remediation_background,
        args=(issue_number, issue_title),
        daemon=True,
        name=f"remediate-{issue_number}",
    )
    thread.start()

    # 9. Return 200 immediately
    return jsonify({
        "received": True,
        "issue_number": issue_number,
        "issue_title": issue_title,
        "status": "remediation_started",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }), 200


# ---------- Health check ----------

@app.route("/health", methods=["GET"])
def health():
    """Quick sanity check that the server is running."""
    with processing_lock:
        currently_processing = list(processing)
    return jsonify({
        "status": "ok",
        "currently_processing": currently_processing,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }), 200


# ---------- Active sessions ----------

@app.route("/status", methods=["GET"])
def status():
    """Show what's currently being processed."""
    with processing_lock:
        currently_processing = list(processing)
    return jsonify({
        "processing_count": len(currently_processing),
        "issues": currently_processing,
    }), 200


# ---------- Entrypoint ----------

if __name__ == "__main__":
    port = int(os.environ.get("WEBHOOK_PORT", 5000))
    log.info(f"Starting webhook server on port {port}")
    log.info(f"Listening for GitHub events on POST /webhook")
    log.info(f"Health check available at GET /health")
    app.run(host="0.0.0.0", port=port, debug=False)