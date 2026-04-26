# Cog Take-Home Notes

## Setup
- Conducted a  test to ensure the API was connected
- Devin API authentication works with token using the service-user key
- Can create sessions via `POST /v3/organizations/{org_id}/sessions`
- Can list all org sessions via `GET /v3/organizations/{org_id}/sessions`
- Can poll a single session via `GET /v3/organizations/{org_id}/sessions/{session_id}`
- Service-user-created sessions don't show in my personal session list by default
 - They ARE visible via the API list endpoint
 - The `user_id` vs `service_user_id` fields cleanly distinguish human-triggered from automation-triggered sessions — useful signal for analytics later
- First successful real session as a demo I had Devin clone `SeanDreifuss/superset`, edited README.md, pushed a branch, opened PR #1
- `pull_requests` array in the session response gives the PR URL directly — no GitHub API call needed
- set Devin to use auto-review on PRs 

## Devin Vocab / Learnings / Questions

## Architecture
Trigger (GitHub webhook on `security-finding` label) → orchestrator → Devin session with Playbook → child session via child_playbook_id does the fix → PR opens → Devin Review runs → orchestrator records outcome →  some sort of digest / analytics

## Issue shortlist
Tier 1 (easy): CVE-2023-27524 SECRET_KEY, CVE-2023-39264 stack traces, CVE-2024-39887 SQLi Postgres funcs, CVE-2023-42502 open redirect
Tier 2 (medium): CVE-2023-36388 SSRF, CVE-2023-46104 ZIP bomb
Tier 3 (escalate): CVE-2023-37941 RCE, CVE-2023-27523 Jinja authz

## Open questions
- Does status_detail=finished auto-end the session?
- How does child_playbook_id actually trigger — in Playbook body or automatic?
- Real ACU cost of one remediation
- Webhooks for session state?
- Does Devin use DeepWiki automatically on public repos?

##  Autonomy Failure Mode Example

- In my test, Devin session was still running as it was "waiting for user to respond" 
    - BLUF: need some sort of trigger to signal termination 

Devin halts at `status: running / status_detail: waiting_for_user` by default after completing visible work — even when the task is functionally done. It waits for a human to confirm or give next instructions.

**Implication for the orchestrator:** I can't rely on Devin to self-terminate. Prompts and Playbooks must be constructed to force autonomous completion.

**Mitigations to test:**
1. Explicit autonomy language in the prompt: "Complete fully and autonomously. Do not ask clarifying questions. End the session when the PR is opened."
2. `structured_output` parameter: instructing Devin to return a defined JSON schema at the end appears to signal session termination (per docs — to be verified).
3. Orchestrator timeout: if a session sits in `waiting_for_user` past N minutes, the orchestrator terminates it and flags the finding for human review.

## Build to do
Day 1: seed issues + write Playbooks + create them via API
Day 2: orchestrator end-to-end on one finding, measure ACU
Day 3: analytics + escalation cases + Docker + README
Day 4: Record Loom + submit

## Test run analytics notes
Tested on issue #3
- Outcome: escalated (correctly)
- Reason: Devin checked the code, confirmed vulnerability is already mitigated
- Key insight: this is the system working well 
- Demo ideas: start with this case to establish "taste" before showing successful fix / more complex case


## Demo artifacts

| Issue | CVE | Outcome | Artifact |
|---|---|---|---|
| #2 | CVE-2023-27524 | PR opened | https://github.com/SeanDreifuss/superset/pull/10 |
| #3 | CVE-2023-39264 | PR opened (test-only) | [new PR URL] |
| #8 | CVE-2023-37941 | Escalated | Session: [URL] |

## Observed behavior: judgment variability

On issue #3, across multiple runs Devin has produced different defensible outcomes:
- Run 1: escalated ("already fixed, recommend closing")
- Run 2: auto-remediated (added missing regression tests to lock in the secure default)

Both are consistent with the Playbook's triage criteria. The variability reflects real latitude in how a senior engineer might interpret "already mitigated." For the demo, the PR-producing run is shown. For a production deployment, this could be tightened by adding an explicit "already-mitigated → always escalate" rule.

## Webhook Notes
The flow:
1. GitHub webhook receiver for security findings.

   - When an engineer files an issue on SeanDreifuss/superset with the
   'security-finding' label, GitHub sends a POST to /webhook.
   - This server receives it and spawns a Devin remediation pipeline.

Usage:
  python3 orchestrator/webhook_server.
