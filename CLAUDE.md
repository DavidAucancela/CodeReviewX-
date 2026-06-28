# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A GitHub App that automatically reviews pull requests. It receives PR webhooks, runs static analysis (Ruff/ESLint) plus a Claude semantic pass over the diff, and posts inline comments back on the PR. Deployed on Railway via Docker; the running instance is at `https://codereviewx-production.up.railway.app`.

## Commands

```bash
# Run locally (auto-reload)
uvicorn app.main:app --reload --port 8000

# Install deps
pip install -r requirements.txt

# Expose local server to GitHub webhooks during dev
ngrok http 8000

# Run via Docker (mounts private-key.pem read-only)
docker-compose up --build
```

There is **no test suite** and no lint config for this repo itself. Ruff/ESLint here are runtime tools used to analyze other people's PRs, not to lint this codebase.

## Request flow

`POST /webhook` (`app/main.py`) is the only real endpoint (`/health` is for uptime checks). The flow:

1. `webhook_handler.verify_signature` — HMAC-SHA256 check against `GITHUB_WEBHOOK_SECRET`. **If the secret is unset, verification is skipped and returns True** (dev convenience, but a footgun in prod).
2. `webhook_handler.parse_pr_event` — only `opened` and `synchronize` actions proceed; everything else returns `{"ignored": True}`.
3. The handler responds `200` **immediately**, then runs `pipeline.run_review_pipeline` in a background thread via `asyncio.to_thread` (the pipeline is sync/blocking — httpx/subprocess/Anthropic calls — so it must not run on the event loop).

`pipeline.run_review_pipeline` orchestrates everything:
- `github_client.get_installation_token` — mints a short-lived JWT from the App private key, exchanges it for an installation access token.
- `github_client.get_pr_files` → `diff_parser.extract_file_contexts` — filters to `SUPPORTED_EXTENSIONS`, skips `removed` files, builds a per-file context with the patch and a `line_map`.
- For each file: `static_analyzer.run_static_analysis` then `semantic_analyzer.analyze_semantically` (Claude).
- `_build_inline_comments` keeps only comments whose line is in `line_map` (i.e. an added `+` line in the diff), then `github_client.post_review` posts a single review with all inline comments.

## Things that aren't obvious

- **Static analysis sees only the added lines, not the whole file.** `pipeline.py` strips the patch down to lines starting with `+` and writes *only those* to a temp file before running Ruff/ESLint. Line numbers from these tools therefore do **not** correspond to real file positions — they're only passed to Claude as supplementary context, never posted directly, so the mismatch is intentional/harmless.
- **`line_map` is the gatekeeper for which comments survive.** `diff_parser.parse_diff_lines` maps real file line numbers → diff position by parsing `@@` hunk headers. Comments from Claude on lines outside the diff are silently dropped. The GitHub review API call uses `line`+`side: RIGHT` (not the computed position).
- **GitHub is called via raw `httpx` + `PyJWT`, not PyGithub.** Despite `PyGithub` being in `requirements.txt`, the actual integration in `github_client.py` is hand-rolled. `jwt` (PyJWT) is only available transitively through PyGithub — it has no direct requirements entry.
- **`llm-observatory` is declared but not yet imported.** It's listed in `requirements.txt` (installed from git: `DavidAucancela/llm-observatory`, `packages/sdk-python`) as groundwork for observability, but no module imports it yet — token/cost tracking is still done manually via `logger` in `semantic_analyzer.py`. Don't assume the SDK is wired into the pipeline.
- **Private key loading is environment-dependent** (`config/settings.py`): `GITHUB_APP_PRIVATE_KEY` (full key with escaped `\n`, used on Railway) takes precedence; otherwise it reads the file at `GITHUB_APP_PRIVATE_KEY_PATH` (defaults to `private-key.pem`, used locally). Railway can't host `.pem` files, hence the env-var path.
- **Claude model is configurable** via `ANTHROPIC_MODEL` (`config/settings.py`), defaulting to `claude-haiku-4-5` (cheaper; set `claude-sonnet-4-6` for max bug-finding). Each per-file diff is truncated to `MAX_PATCH_CHARS` before the call, and token usage is logged per file. The prompt forces a JSON-array response (comments use a fixed *Qué pasa / Por qué importa / Sugerencia* + severity structure); the parser strips markdown fences and discards anything that isn't valid JSON (failures degrade to "no comments", never raise).
- **Code and comments are in Spanish**; log messages and user-facing PR comments are Spanish too. Match that when editing.

## Environment variables

`GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, and one of `GITHUB_APP_PRIVATE_KEY` / `GITHUB_APP_PRIVATE_KEY_PATH`. `PORT` defaults to 8000. Optional cost knobs: `ANTHROPIC_MODEL` (defaults to `claude-haiku-4-5`) and `MAX_PATCH_CHARS` (defaults to 12000). See `.env.example`. Supported file extensions live in `config/settings.py` (`.py`, `.js`, `.ts`, `.jsx`, `.tsx`).
