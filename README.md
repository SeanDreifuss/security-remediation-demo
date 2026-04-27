# Devin Vulnerability Remediation

**Demo:** [Watch the Loom walkthrough](https://www.loom.com/share/27228dde25e64c858d4fafd70680a3e3) | **Superset Fork:** [SeanDreifuss/superset](https://github.com/SeanDreifuss/superset)


An automated vulnerability remediation system that uses Devin AI to triage and fix security findings in GitHub repositories. When a security finding is reported via a GitHub issue with the `security-finding` label, the system automatically analyzes the issue and either applies a fix with a pull request or escalates it to human engineers for complex cases.

## Quickstart

The fastest way to see this system in action:

**Watch the demo:** [Loom walkthrough](YOUR_LOOM_URL) shows the full pipeline — webhook trigger, triage session, auto-remediation, and escalation.

**Run a single remediation via CLI** (requires Devin API credentials):

```bash
git clone https://github.com/SeanDreifuss/security-remediation-demo.git
cd security-remediation-demo
pip install -r requirements.txt
cp .env.example .env
# Fill in DEVIN_API_KEY, DEVIN_ORG_ID, TRIAGE_PLAYBOOK_ID, FIX_PLAYBOOK_ID
python3 scripts/run_remediation.py 2
```

This processes issue #2 from [SeanDreifuss/superset](https://github.com/SeanDreifuss/superset) — a real CVE-2023-27524 finding — through the full triage and fix pipeline. Devin will open a pull request on the fork automatically.

**Run with Docker:**

```bash
cp .env.example .env  # fill in credentials
docker-compose up
```

Then create an issue on [SeanDreifuss/superset](https://github.com/SeanDreifuss/superset) with the `security-finding` label to trigger the webhook pipeline.

> **Note:** Requires a Devin API key. The Playbook IDs (`TRIAGE_PLAYBOOK_ID`, `FIX_PLAYBOOK_ID`) are created by running `python3 scripts/setup_playbooks.py` once against your own Devin org. The seeded issues and demo PRs are pre-configured on the `SeanDreifuss/superset` fork.
## Overview

This system orchestrates a two-phase remediation pipeline:

1. **Triage Phase**: A Devin session analyzes the security finding to determine if it can be auto-remediated
2. **Fix Phase** (if auto-remediable): A second Devin session applies the minimal fix and opens a pull request

The system is designed to handle bounded, mechanical security fixes automatically while escalating complex or architectural issues that require human judgment.

## Architecture

```
GitHub Webhook (issue labeled with 'security-finding')
    ↓
Flask Webhook Server (orchestrator/webhook_server.py)
    ↓
Devin Triage Session (Security Finding Triage Playbook)
    ↓
    ├─→ Escalated (complex issue) → Post comment to GitHub issue
    │
    └─→ Auto-remediate → Devin Fix Session (Security Fix Application Playbook)
            ↓
        GitHub Pull Request
```

### Components

- **orchestrator/webhook_server.py** - Flask server that receives GitHub webhook events and spawns background remediation threads
- **scripts/run_remediation.py** - Core remediation pipeline logic, reusable from CLI or webhook
- **scripts/setup_playbooks.py** - One-time setup script to create Triage and Fix playbooks on Devin
- **scripts/analytics.py** - Analytics script to report on remediation metrics

### Devin Playbooks

The system uses two Devin playbooks:

1. **Security Finding Triage** (`!security-triage`) - Analyzes security findings and decides whether to auto-remediate or escalate
2. **Security Fix Application** (`!security-fix`) - Applies scoped security fixes and opens pull requests

See [playbooks.md](playbooks.md) for detailed playbook specifications.

## Setup

### Prerequisites

- Python 3.9+
- Devin API credentials
- Target GitHub repository

### 1. Clone the Repository

```bash
git clone <repository-url>
cd security-remediation-demo
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Or create a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with the following variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `DEVIN_API_KEY` | Your Devin API key | `cog_your_key_here` |
| `DEVIN_ORG_ID` | Your Devin organization ID | `org_your_org_id_here` |
| `GITHUB_TARGET_REPO` | Target repository for remediation | `SeanDreifuss/superset` |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for webhook verification | Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `WEBHOOK_PORT` | Port for webhook server | `5000` |
| `TRIAGE_PLAYBOOK_ID` | ID of the Triage playbook (set after running setup) | `pb_abc123` |
| `FIX_PLAYBOOK_ID` | ID of the Fix playbook (set after running setup) | `pb_def456` |

### 4. Create Devin Playbooks

Run the setup script to create the required playbooks on Devin:

```bash
python3 scripts/setup_playbooks.py
```

This will output the playbook IDs. Add them to your `.env` file:

```
TRIAGE_PLAYBOOK_ID=pb_abc123
FIX_PLAYBOOK_ID=pb_def456
```

### 5. Configure GitHub Webhook

The demo is pre-configured to work with [`SeanDreifuss/superset`](https://github.com/SeanDreifuss/superset), which contains 8 seeded security findings.

**To simulate the workflow locally**, you can trigger remediation directly via CLI without a webhook:

```bash
python3 scripts/run_remediation.py <issue_number>
```

For example:
```bash
python3 scripts/run_remediation.py 2
```

**To run with webhook automation** (requires your own fork):
1. Fork the target repository to your own GitHub account
2. Go to your fork's Settings → Webhooks → Add webhook
3. Set payload URL to `https://your-ngrok-url/webhook`
4. Set content type to `application/json`
5. Add your `GITHUB_WEBHOOK_SECRET` as the webhook secret
6. Select **Issues** as the trigger event
7. Update `TARGET_REPO` in `scripts/run_remediation.py` to point to your fork

## Usage

### Running the Webhook Server

Start the Flask webhook server:

```bash
python3 orchestrator/webhook_server.py
```

The server will:
- Listen for GitHub webhook events on `POST /webhook`
- Provide a health check at `GET /health`
- Show current processing status at `GET /status`
- Log all activity to stdout and `webhook.log`

### Running a Single Remediation via CLI

To manually trigger remediation for a specific issue:

```bash
python3 scripts/run_remediation.py <issue_number>
```

Example:

```bash
python3 scripts/run_remediation.py 4
```

This will:
1. Fetch the issue from GitHub
2. Create a Triage session on Devin
3. Poll the session until completion
4. If auto-remediated, create a Fix session
5. Report the outcome (PR URL or escalation reason)

### Running Analytics

To view remediation metrics:

```bash
python3 scripts/analytics.py
```

This reports on:
- Number of findings processed
- Auto-remediation rate (PRs opened)
- Escalation rate
- Mean time to PR
- ACU cost per finding

## Docker Deployment

### Using Docker Compose (Recommended)

Build and run the webhook server using Docker Compose:

```bash
docker-compose up -d
```

This will:
- Build the webhook server image
- Start the container on port 5000
- Use environment variables from `.env` file
- Persist logs to a volume

View logs:

```bash
docker-compose logs -f
```

Stop the service:

```bash
docker-compose down
```

### Using Docker Directly

Build the image:

```bash
docker build -t devin-remediation-webhook .
```

Run the container:

```bash
docker run -d \
  --name devin-webhook \
  --env-file .env \
  -p 5000:5000 \
  -v $(pwd)/webhook.log:/app/webhook.log \
  devin-remediation-webhook
```

## How It Works

### Triage Criteria

The Triage playbook evaluates whether a finding can be auto-remediated based on:

1. **Scope**: Is the fix bounded to 1-3 files?
2. **Complexity**: Is the fix mechanical (validation, config, input check) rather than architectural?
3. **Risk**: Would the fix break existing legitimate behavior?

If all criteria favor a bounded mechanical fix, it proceeds to auto-remediation. Otherwise, it escalates to human engineers.

### Escalation is Not Failure

A correctly-escalated finding is a successful outcome. The system is designed to handle only the cases it can fix safely and confidently.

### Session Management

- Webhook events spawn background threads to avoid GitHub's 10-second timeout
- Duplicate events for the same issue are deduplicated
- Sessions are tagged with `issue-<number>` and `triage`/`fix` for tracking
- Structured output ensures clean communication between phases

## Troubleshooting

### Webhook Signature Verification Fails

Ensure `GITHUB_WEBHOOK_SECRET` in `.env` matches the secret configured in GitHub webhook settings.

### Sessions Hang in "waiting_for_user"

This can happen if Devin prompts for clarification. Mitigations:
- Use explicit autonomy language in playbooks
- The orchestrator will timeout and flag for human review
- Review playbook prompts for ambiguity

### Playbook IDs Not Found

Run `python3 scripts/setup_playbooks.py` to create the playbooks and update your `.env` file with the returned IDs.

### Permission Errors

Ensure:
- GitHub token has `repo` scope
- Devin service user has access to the target repository
- Webhook server can reach Devin API (no firewall blocking)

## Development

### Project Structure

```
.
├── orchestrator/
│   └── webhook_server.py      # Flask webhook receiver
├── scripts/
│   ├── run_remediation.py     # Core remediation pipeline
│   ├── setup_playbooks.py     # Playbook creation script
│   └── analytics.py           # Analytics reporter
├── playbooks.md               # Detailed playbook specifications
├── .env.example               # Environment variable template
├── Dockerfile                 # Container definition
├── docker-compose.yml         # Container orchestration
└── README.md                  # This file
```

### Adding New Playbooks

To add new remediation playbooks:

1. Define the playbook specification in a markdown file
2. Add a creation function in `scripts/setup_playbooks.py`
3. Update the pipeline logic in `scripts/run_remediation.py` to invoke the new playbook
4. Add the playbook ID to `.env`
5. Alternatively, create the playbook directly in the Devin UI and add the ID to `.env`
