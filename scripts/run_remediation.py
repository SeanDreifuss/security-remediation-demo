"""
Runs one GitHub issue through the full remediation flow:
  GitHub issue → Triage session → (if auto-remediate) Fix session → PR

Usage:
  python3 scripts/run_remediation.py <issue_number>

Example:
  python3 scripts/run_remediation.py 2
"""
import json
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

DEVIN_API_KEY = os.environ["DEVIN_API_KEY"]
DEVIN_ORG_ID = os.environ["DEVIN_ORG_ID"]
TRIAGE_PLAYBOOK_ID = os.environ["TRIAGE_PLAYBOOK_ID"]
FIX_PLAYBOOK_ID = os.environ["FIX_PLAYBOOK_ID"]
TARGET_REPO = "SeanDreifuss/superset"

DEVIN_BASE = "https://api.devin.ai/v3"
GITHUB_BASE = "https://api.github.com"

DEVIN_HEADERS = {
    "Authorization": f"Bearer {DEVIN_API_KEY}",
    "Content-Type": "application/json",
}

POLL_INTERVAL_SECONDS = 20
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes


# ---------- Structured output schemas ----------

TRIAGE_SCHEMA = {
    "type": "object",
    "required": ["outcome", "reasoning"],
    "properties": {
        "outcome": {"enum": ["auto_remediate_requested", "escalated", "failed"]},
        "cve_reference": {"type": "string"},
        "affected_files": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        "escalation_reason": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "recommended_approach": {"type": ["string", "null"]},
    },
}

FIX_SCHEMA = {
    "type": "object",
    "required": ["outcome", "reasoning"],
    "properties": {
        "outcome": {"enum": ["fix_applied", "needs_escalation", "failed"]},
        "pr_url": {"type": ["string", "null"]},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "test_added": {"type": "boolean"},
        "test_gap_reason": {"type": ["string", "null"]},
        "cve_reference": {"type": "string"},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


# ---------- GitHub helpers ----------

def fetch_issue(issue_number: int) -> dict:
    """Fetch an issue from the fork. No auth needed for public repos."""
    url = f"{GITHUB_BASE}/repos/{TARGET_REPO}/issues/{issue_number}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


# ---------- Devin helpers ----------

def create_session(prompt: str, playbook_id: str, schema: dict, tags: list[str]) -> str:
    """Create a Devin session. Returns session_id."""
    payload = {
        "prompt": prompt,
        "playbook_id": playbook_id,
        "repos": [TARGET_REPO],
        "structured_output_schema": schema,
        "max_acu_limit": 5,
        "tags": tags,
    }
    response = requests.post(
        f"{DEVIN_BASE}/organizations/{DEVIN_ORG_ID}/sessions",
        headers=DEVIN_HEADERS,
        json=payload,
    )
    response.raise_for_status()
    return response.json()["session_id"]


def poll_session(session_id: str) -> dict:
    """Poll a session until it reaches a terminal state. Returns final session object."""
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        if elapsed > SESSION_TIMEOUT_SECONDS:
            raise TimeoutError(
                f"Session {session_id} did not finish within "
                f"{SESSION_TIMEOUT_SECONDS}s"
            )

        response = requests.get(
            f"{DEVIN_BASE}/organizations/{DEVIN_ORG_ID}/sessions/{session_id}",
            headers=DEVIN_HEADERS,
        )
        response.raise_for_status()
        session = response.json()

        status = session.get("status")
        detail = session.get("status_detail")
        acus = session.get("acus_consumed", 0)

        print(f"  [{elapsed:4d}s] status={status} detail={detail} acus={acus:.3f}")

        # Terminal: done
        if status == "exit":
            return session

        # Terminal: failed
        if status == "error":
            return session

        # Task complete but session still "running" — grab structured output, then break
        if status == "running" and detail == "finished":
            return session

        # Stuck waiting for user input — abort
        if status == "running" and detail == "waiting_for_user":
            print("  Session is waiting for user input. Aborting.")
            return session

        # Suspended for any non-resolvable reason
        if status == "suspended":
            print(f"  Session suspended ({detail}). Returning.")
            return session

        time.sleep(POLL_INTERVAL_SECONDS)


# ---------- Prompt builders ----------

def build_triage_prompt(issue: dict) -> str:
    return f"""A new security finding has been filed as GitHub issue #{issue['number']} on {TARGET_REPO}.

Issue title: {issue['title']}

Issue body:
---
{issue['body']}
---

Triage this finding per the Security Finding Triage playbook. Return structured output when complete."""


def build_fix_prompt(issue: dict, triage_output: dict) -> str:
    return f"""A security finding has been triaged and scoped for remediation.

Originating issue: #{issue['number']} on {TARGET_REPO}
Issue title: {issue['title']}

Issue body:
---
{issue['body']}
---

Triage session's structured output:
---
{json.dumps(triage_output, indent=2)}
---

Apply the fix per the Security Fix Application playbook. Reference the originating issue with `Fixes #{issue['number']}` in the PR body. Return structured output when complete."""


# ---------- Main flow ----------

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/run_remediation.py <issue_number>")
        sys.exit(1)

    issue_number = int(sys.argv[1])

    print(f"[1] Fetching issue #{issue_number} from {TARGET_REPO}...")
    issue = fetch_issue(issue_number)
    print(f"    Title: {issue['title']}")

    print(f"\n[2] Creating triage session...")
    triage_session_id = create_session(
        prompt=build_triage_prompt(issue),
        playbook_id=TRIAGE_PLAYBOOK_ID,
        schema=TRIAGE_SCHEMA,
        tags=[f"issue-{issue_number}", "triage"],
    )
    print(f"    Session: {triage_session_id}")
    print(f"    URL: https://app.devin.ai/sessions/{triage_session_id}")

    print(f"\n[3] Polling triage session until terminal...")
    triage_session = poll_session(triage_session_id)

    triage_output = triage_session.get("structured_output")
    print(f"\n[4] Triage complete.")
    print(f"    Structured output:")
    print(json.dumps(triage_output, indent=6))

    if not triage_output:
        print("    No structured output returned. Cannot continue.")
        sys.exit(1)

    outcome = triage_output.get("outcome")

    if outcome == "escalated":
        print(f"\n[5] Triage escalated this finding. Stopping here.")
        print(f"    Reason: {triage_output.get('escalation_reason')}")
        return

    if outcome != "auto_remediate_requested":
        print(f"\n[5] Triage returned unexpected outcome: {outcome}. Stopping.")
        return

    print(f"\n[5] Triage requested auto-remediation. Creating fix session...")
    fix_session_id = create_session(
        prompt=build_fix_prompt(issue, triage_output),
        playbook_id=FIX_PLAYBOOK_ID,
        schema=FIX_SCHEMA,
        tags=[f"issue-{issue_number}", "fix"],
    )
    print(f"    Session: {fix_session_id}")
    print(f"    URL: https://app.devin.ai/sessions/{fix_session_id}")

    print(f"\n[6] Polling fix session until terminal...")
    fix_session = poll_session(fix_session_id)

    fix_output = fix_session.get("structured_output")
    print(f"\n[7] Fix session complete.")
    print(f"    Structured output:")
    print(json.dumps(fix_output, indent=6))

    if fix_output and fix_output.get("pr_url"):
        print(f"\n✅ PR opened: {fix_output['pr_url']}")
    else:
        print(f"\n⚠️  No PR URL returned.")


if __name__ == "__main__":
    main()