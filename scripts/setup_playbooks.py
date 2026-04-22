"""
One-time setup script.
Creates the Triage and Fix Playbooks on Devin and prints their IDs.
Copy the printed IDs into your .env file.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["DEVIN_API_KEY"]
ORG_ID = os.environ["DEVIN_ORG_ID"]
BASE_URL = "https://api.devin.ai/v3"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


TRIAGE_BODY = r"""
## Overview
Identify an automated security scanner finding for Apache Superset (fork: SeanDreifuss/superset). Decide whether the finding can be auto-remediated or must be escalated to a human security engineer. If auto-remediable, orchestrate the fix via the Security Fix Application playbook. Return structured output summarizing the decision and outcome.

## What's Needed From User
The orchestrator will provide, via the session prompt:
- A security finding in GitHub issue format (severity, affected file, category, suggested remediation, CVE reference)
- The originating GitHub issue number on SeanDreifuss/superset

The target repository (SeanDreifuss/superset) will be passed via the `repos` parameter on session creation.

This session runs in an automated orchestrator context. There is no human user. All required inputs are in the prompt and the `repos` parameter.

## Procedure
1. Read the security finding in the prompt and extract: CVE reference, severity, affected file, category, and suggested remediation.
2. Use DeepWiki to locate the affected file in SeanDreifuss/superset and read its surrounding code.
3. Assess the fix's scope using these criteria:
   - Is the fix bounded to 1-3 files?
   - Is the fix mechanical (validation, config, input check) rather than architectural (migration, refactor, protocol change)?
   - Would the fix break existing legitimate behavior?
4. Decide: AUTO-REMEDIATE or ESCALATE.
   - AUTO-REMEDIATE if all three criteria above favor a bounded mechanical fix
   - ESCALATE if the fix requires architectural decisions, touches more than 3 files, or requires a data migration
5. If AUTO-REMEDIATE: return structured output with outcome: auto_remediate_requested, populating affected_files and recommended_approach. The orchestrator will create the fix session.
6. If ESCALATE: return structured output with outcome: escalated and a clear escalation_reason. The orchestrator will post a comment on the originating GitHub issue.
7. Return structured output reflecting the outcome.

## Specifications
When complete, the following must be true:
- Exactly one of the following is reflected in the structured output:
  - `outcome: auto_remediate_requested` with populated `affected_files` and `recommended_approach`, OR
  - `outcome: escalated` with populated `escalation_reason` (the orchestrator will post the comment based on this)
- No files in SeanDreifuss/superset have been modified by this session
- No pull request has been opened by this session
- The session ends without waiting for user input

## Advice and Pointers
- Escalation is not a failure. A correctly-escalated finding is a successful outcome.
- Use DeepWiki before reading files directly — it is faster for initial orientation on unfamiliar code.
- If the finding's suggested remediation does not match what the code actually needs, trust the code over the scanner. Note the discrepancy in `reasoning`.
- The CVE reference is informative but secondary. The scanner's description of the current code is what matters for triage.

## Forbidden Actions
- Do NOT modify files in SeanDreifuss/superset directly in this session.
- Do NOT open pull requests from this session.
- Do NOT post comments on GitHub issues. The orchestrator handles all side effects based on your structured output.
- Do NOT ask clarifying questions. If a finding is ambiguous, make a documented judgment call and record it in `reasoning`.
- Do NOT wait for user confirmation after completing the triage. Return structured output and end.
- Do NOT attempt to create additional Devin sessions. This session only performs triage.
"""


FIX_BODY = r"""
## Overview
Apply a minimal, scoped security fix to Apache Superset (fork: SeanDreifuss/superset) based on a prior triage decision. Open a pull request with the fix and (if feasible) a regression test. Return structured output summarizing the outcome.

## What's Needed From User
The orchestrator provides, via the session prompt:
- The original security finding body (severity, category, suggested remediation, CVE reference)
- The triage session's structured output, including:
  - `affected_files` — the files scoped for this fix
  - `recommended_approach` — the approach identified during triage
- The originating GitHub issue number (for PR cross-reference)

The target repository (`SeanDreifuss/superset`) is passed via the `repos` parameter.

This session runs in an automated orchestrator context. There is no human user. All inputs required are in the prompt.

## Procedure
1. Read the triage context from the prompt. Note the `affected_files` and `recommended_approach`.
2. Read each affected file fully before editing. Understand the surrounding code.
3. Identify existing patterns in the file or module that the fix should match (validation helpers, error classes, config patterns, etc.).
4. Apply the minimal fix following the recommended approach. Scope changes to the files listed in `affected_files`.
5. Locate the corresponding test file(s) and examine existing test patterns.
6. Add a regression test that fails against the vulnerable behavior and passes against your fix, if feasible given existing test infrastructure. If not feasible, document the gap in the PR body.
7. Open a pull request against `main` with:
   - Title format: `[SECURITY] {short description of fix} ({CVE ID from finding})`
   - Example: `[SECURITY] Reject known-default SECRET_KEY on startup (CVE-2023-27524)`
   - Body containing: summary of vulnerability, description of fix, files changed, testing notes, `Fixes #<issue_number>`, CVE reference
   - Labels: `security`, `auto-remediation`
8. Return structured output reflecting the outcome.

## Specifications
When complete, the following must be true:
- Changes are confined to files listed in `affected_files` from the triage context.
- A pull request exists against `main` in SeanDreifuss/superset, referencing the originating issue with `Fixes #N`.
- The PR body documents the fix, the files changed, and either the regression test added or the reason no test was added.
- Structured output is returned with `outcome` set and `pr_url` populated if `outcome == fix_applied`.
- The session ends without waiting for user input.

## Advice and Pointers
- The triage session has already determined this fix is bounded. Trust the scope but stop if reality diverges.
- If the fix turns out to be more complex than triage assumed (e.g., requires changing unlisted files, or touches architectural concerns), STOP immediately. Return `outcome: needs_escalation` with reasoning. Do not force a partial fix.
- If a regression test is not feasible given existing test infrastructure, document why in the PR body. Do not invent fragile tests for the sake of checking a box.
- Match existing code patterns. Look at similar validators, handlers, or config additions before writing new code.
- Reference the originating issue with `Fixes #N` in the PR body so merging the PR auto-closes the issue.
- If you encounter an error that prevents completing the fix (e.g., the affected file doesn't exist, unexpected repo state), return `outcome: failed` with a clear `reasoning`. Do not silently partially complete.

## Forbidden Actions
- Do NOT merge the pull request. Opening it is the goal.
- Do NOT modify files outside `affected_files`.
- Do NOT change CI configuration, package versions, or unrelated dependencies unless the fix specifically requires it.
- Do NOT refactor unrelated code or fix other bugs you notice in passing.
- Do NOT re-run or modify unrelated tests that happen to fail due to pre-existing issues. Document these in the PR body rather than fixing them.
- Do NOT ask clarifying questions. Make documented judgment calls and proceed.
- Do NOT wait for user confirmation after opening the PR. Return structured output and end.
- Do NOT force a partial fix if the scope is wrong. Escalate cleanly via `outcome: needs_escalation`.
"""


def create_playbook(title, macro, body):
    response = requests.post(
        f"{BASE_URL}/organizations/{ORG_ID}/playbooks",
        headers=HEADERS,
        json={
            "title": title,
            "macro": macro,
            "body": body.strip(),
        },
    )
    response.raise_for_status()
    data = response.json()
    return data["playbook_id"]


if __name__ == "__main__":
    print("Creating Triage Playbook...")
    triage_id = create_playbook(
        title="Security Finding Triage",
        macro="!security-triage",
        body=TRIAGE_BODY,
    )
    print(f"  Created: {triage_id}")

    print("Creating Fix Playbook...")
    fix_id = create_playbook(
        title="Security Fix Application",
        macro="!security-fix",
        body=FIX_BODY,
    )
    print(f"  Created: {fix_id}")

    print("\nAdd these to your .env file:")
    print(f"TRIAGE_PLAYBOOK_ID={triage_id}")
    print(f"FIX_PLAYBOOK_ID={fix_id}")
    