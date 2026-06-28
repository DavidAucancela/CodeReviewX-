# CodeReviewX

Automated code review bot deployed as a GitHub App. Listens to pull request webhooks, analyzes diffs with static analysis tools and Claude AI, and posts inline comments directly on the PR.

## Features

- **Automatic trigger** — runs on every PR `opened` or `synchronize` event
- **Inline comments** — posts comments on the exact lines with issues, not just a summary
- **Static analysis**
  - Python: [Ruff](https://github.com/astral-sh/ruff) for linting and style issues
  - JavaScript/TypeScript: ESLint for code quality checks
- **Semantic analysis with Claude** — detects logic bugs, unhandled edge cases, security issues (injection, exposed secrets, missing validation), and poorly designed async patterns
- **Multi-language support** — `.py`, `.js`, `.ts`, `.jsx`, `.tsx`
- **HMAC signature verification** — validates every webhook payload with `sha256=` signature
- **Non-blocking pipeline** — webhook responds immediately; analysis runs in background via `asyncio`
- **Health endpoint** — `GET /health` returns `{"status": "ok"}` for uptime monitoring

## Architecture

```
GitHub PR event
      │
      ▼
POST /webhook (FastAPI)
      │
      ├── verify_signature (HMAC-SHA256)
      ├── parse_pr_event (filter opened/synchronize)
      │
      ▼
run_review_pipeline (background task)
      │
      ├── get_installation_token (JWT → GitHub API)
      ├── get_pr_files (list changed files)
      ├── extract_file_contexts (filter + parse diffs)
      │
      └── for each file:
            ├── run_static_analysis (ruff / eslint)
            ├── analyze_semantically (Claude, configurable model)
            └── post_review (inline comments on PR)
```

## Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI + Uvicorn |
| GitHub integration | PyGithub + custom JWT auth |
| AI analysis | Anthropic Claude (configurable, defaults to `claude-haiku-4-5`) |
| Static analysis (Python) | Ruff |
| Static analysis (JS/TS) | ESLint |
| Observability | llm-observatory (opt-in token/cost metrics) |
| HTTP client | httpx |
| Deploy | Railway (Docker) |

## Setup

### 1. Create a GitHub App

Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**

Required permissions:
- **Contents**: Read-only
- **Metadata**: Read-only
- **Pull requests**: Read and write

Subscribe to events:
- **Pull request**

Set the Webhook URL to your server URL + `/webhook`.

### 2. Environment variables

```env
GITHUB_APP_ID=your_app_id
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----
GITHUB_WEBHOOK_SECRET=your_webhook_secret
ANTHROPIC_API_KEY=your_anthropic_key

# Optional cost knobs
ANTHROPIC_MODEL=claude-haiku-4-5   # cheaper default; use claude-sonnet-4-6 for max bug-finding
MAX_PATCH_CHARS=12000              # per-file diff truncation limit

# Optional observability (llm-observatory) — requires Python >= 3.10 when set
OBSERVATORY_TOKEN=obs_sk_...       # leave empty to disable metrics
OBSERVATORY_URL=https://llm-web-production.up.railway.app
```

> For local development, you can use `GITHUB_APP_PRIVATE_KEY_PATH=private-key.pem` and place the `.pem` file in the project root instead.

### 3. Local development

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in your values
uvicorn app.main:app --reload --port 8000
```

To expose your local server to GitHub webhooks:
```bash
ngrok http 8000
```

### 4. Deploy to Railway

1. Connect your GitHub repo in Railway → New Project
2. Set the environment variables (use `GITHUB_APP_PRIVATE_KEY` with the full key content — Railway doesn't support `.pem` files)
3. Railway auto-deploys on every push to `main`
4. Update the Webhook URL in your GitHub App settings to `https://your-app.up.railway.app/webhook`

To get your private key as a single-line string for Railway:
```bash
awk 'NF {printf "%s\\n", $0}' private-key.pem
```

### 5. Install the GitHub App

Go to your GitHub App → **Install App** → select the repositories where you want automated reviews.

## Project structure

```
├── app/
│   ├── main.py              # FastAPI app, webhook endpoint
│   ├── webhook_handler.py   # Signature verification, event parsing
│   ├── pipeline.py          # Review orchestration
│   ├── diff_parser.py       # PR diff parsing, line mapping
│   ├── static_analyzer.py   # Ruff + ESLint runners
│   └── semantic_analyzer.py # Claude AI analysis
├── config/
│   └── settings.py          # Environment config, private key loader
├── Dockerfile
├── docker-compose.yml       # Local Docker dev
└── requirements.txt
```

## How it works

1. A PR is opened or updated in a repo where the App is installed
2. GitHub sends a `POST /webhook` event signed with HMAC-SHA256
3. The bot verifies the signature, parses the event, and responds `200 OK` immediately
4. In the background, the bot fetches the list of changed files from the GitHub API
5. For each supported file, it extracts the diff and runs static analysis
6. The diff and static issues are sent to Claude, which identifies real bugs and security problems
7. Comments are mapped to their exact line numbers in the diff
8. The bot posts a single PR review with all inline comments via the GitHub API
