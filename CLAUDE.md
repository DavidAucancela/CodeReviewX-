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
- For each file: `static_analyzer.run_static_analysis` then `semantic_analyzer.analyze_semantically` (LLM call — Claude or OpenAI, see `LLM_PROVIDER` below).
- `_build_inline_comments` keeps only comments whose line is in `line_map` (i.e. an added `+` line in the diff). All candidates across all files are then sorted by severity (🔴 > 🟡 > 🔵) and truncated to `MAX_INLINE_COMMENTS` before `github_client.post_review` posts a single review — see the cap note below.

## Things that aren't obvious

- **Static analysis sees only the added lines, not the whole file.** `pipeline.py` strips the patch down to lines starting with `+` and writes *only those* to a temp file before running Ruff/ESLint. Line numbers from these tools therefore do **not** correspond to real file positions — they're only passed to Claude as supplementary context, never posted directly, so the mismatch is intentional/harmless.
- **`line_map` is the gatekeeper for which comments survive.** `diff_parser.parse_diff_lines` maps real file line numbers → diff position by parsing `@@` hunk headers. Comments from Claude on lines outside the diff are silently dropped. The GitHub review API call uses `line`+`side: RIGHT` (not the computed position).
- **GitHub is called via raw `httpx` + `PyJWT`, not PyGithub.** Despite `PyGithub` being in `requirements.txt`, the actual integration in `github_client.py` is hand-rolled. `jwt` (PyJWT) is only available transitively through PyGithub — it has no direct requirements entry.
- **The semantic-analysis provider is switchable via `LLM_PROVIDER`** (`config/settings.py`, `anthropic` default or `openai`). `semantic_analyzer.py` branches on it in two places: `_build_client()` picks which SDK/client to construct, and `analyze_semantically()` picks the call shape — Anthropic uses `client.messages.create(system=..., messages=[...])` and reads `message.usage.input_tokens`/`message.content[0].text`; OpenAI uses `client.chat.completions.create(messages=[{"role":"system",...}, {"role":"user",...}])` and reads `response.usage.prompt_tokens`/`response.choices[0].message.content`. Both branches share the same prompt templates, JSON-array parsing, and markdown-fence stripping — only the request/response shape differs. `MODEL` (module-level in `semantic_analyzer.py`) resolves to `OPENAI_MODEL` or `ANTHROPIC_MODEL` depending on the provider.
- **Client is conditionally wrapped by `llm-observatory`, for either provider.** `semantic_analyzer._build_client()` picks the client from `OBSERVATORY_TOKEN` (`config/settings.py`): with a non-blank token (it `.strip()`s, so whitespace counts as unset) it lazily imports `MonitoredAnthropic` or `MonitoredOpenAI` from `llm_observatory` (matching `LLM_PROVIDER`) and sends usage/cost metrics to `OBSERVATORY_URL` (tagged `app=codereviewx`); otherwise it returns a plain `anthropic.Anthropic`/`openai.OpenAI` client (no metrics). The whole wrap is in a `try/except` that **falls back to the plain client on any failure** (SDK missing, bad URL/token, Python < 3.10) and logs it — observability must never stop the bot from reviewing. Both branches log whether metrics are on/off (`LLM Observatory activado/desactivado`). The wrapper proxies the create call and **returns the unmodified SDK response**, so the usual response fields keep working; metric send is fire-and-forget (daemon thread → `POST {OBSERVATORY_URL}/api/metrics` with a `Bearer` token) and never blocks a review.
- **`llm-observatory` (the SDK) requires Python ≥ 3.10.** It uses PEP 604 `X | None` syntax at module load, which raises `TypeError` on 3.9. Production is fine (Docker `python:3.12-slim`). On a local 3.9 interpreter **with `OBSERVATORY_TOKEN` set** the import fails — but `_build_client`'s `try/except` catches it, logs the error, and falls back to the plain Anthropic client, so the bot still runs (just without metrics). Use a 3.10+ venv locally if you actually want metrics.
- **Observatory cost is model-ID-sensitive.** The SDK's `_pricing.py` matches model IDs exactly and only knows the **dated** Haiku id `claude-haiku-4-5-20251001`, not the alias `claude-haiku-4-5`. Sending the alias logs `Unknown Anthropic model pricing … cost recorded as $0` (tokens are still recorded; only `cost_usd` is 0). That's why **Railway sets `ANTHROPIC_MODEL=claude-haiku-4-5-20251001`** even though the code default is the alias. `claude-sonnet-4-6` is in the table without a date, so Sonnet isn't affected.
- **Private key loading is environment-dependent** (`config/settings.py`): `GITHUB_APP_PRIVATE_KEY` (full key with escaped `\n`, used on Railway) takes precedence; otherwise it reads the file at `GITHUB_APP_PRIVATE_KEY_PATH` (defaults to `private-key.pem`, used locally). Railway can't host `.pem` files, hence the env-var path.
- **Model is configurable per provider** via `ANTHROPIC_MODEL` (default `claude-haiku-4-5`; set `claude-sonnet-4-6` for max bug-finding) or `OPENAI_MODEL` (default `gpt-4o-mini`; set `gpt-4o` for max bug-finding), whichever matches `LLM_PROVIDER` (`config/settings.py`). In production Railway overrides `ANTHROPIC_MODEL` to the dated `claude-haiku-4-5-20251001` so Observatory records real cost (see the model-ID note above) — `OPENAI_MODEL`'s ids (`gpt-4o-mini`, `gpt-4o`, ...) are already exact matches in the SDK's pricing table, no dated variant needed. Each per-file diff is truncated to `MAX_PATCH_CHARS` before the call, and token usage is logged per file. The prompt forces a JSON-array response (comments use a fixed *Qué pasa / Por qué importa / Sugerencia* + severity structure); the parser strips markdown fences and discards anything that isn't valid JSON (failures degrade to "no comments", never raise) — this parsing is shared by both providers.
- **Switching `LLM_PROVIDER` is the escape hatch when one account runs out of credit.** Both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` can be set at the same time; only the one matching `LLM_PROVIDER` is used. No code change needed to switch — just flip the env var (and redeploy/restart) on Railway.
- **Code and comments are in Spanish**; log messages and user-facing PR comments are Spanish too. Match that when editing.
- **Inline comments are capped globally, not per file.** `pipeline._build_inline_comments` tags each candidate with a severity rank parsed from the emoji in its body (🔴=0, 🟡=1, 🔵=2, unknown=3). `_run_review_pipeline` pools candidates from every file, sorts by that rank, and posts only the top `MAX_INLINE_COMMENTS` (default 15) as inline PR comments — this exists because large PRs used to generate 100+ inline comments. Nothing is silently lost: `_build_summary` lists every finding per file (even the ones cut by the cap) in the review body, and states how many were shown inline vs. summary-only.
- **Four opt-in cost controls, all off by default, combinable.** For PRs with many changed files (large diffs → many Claude calls):
  - `ONLY_CRITICAL_SEVERITY=true` injects `_CRITICAL_ONLY_INSTRUCTION` into the user prompt (`semantic_analyzer.py`) so Claude only reports 🔴 findings, skipping 🟡/🔵 entirely — fewer output tokens, no extra API calls.
  - `TWO_PASS_MODE=true` skips the Claude call for a file when `run_static_analysis` found nothing on its added lines (`pipeline._run_review_pipeline`) — clean files cost $0.
  - `RISKY_FILES_ONLY=true` skips the Claude call unless `pipeline._is_risky_file` matches: filename contains a substring from `RISKY_FILE_PATTERNS` (default `auth,payment,pago,db,database,secret,crypto,session,token`), or the file has more than `RISKY_PATCH_SIZE` (default 300) new lines.
  - `MAX_PATCH_CHARS` (pre-existing) truncates the diff sent per file; lowering it (e.g. 5000) reduces tokens at the cost of missing subtler issues.
  - Skipped files still get static analysis (Ruff/ESLint) and show up in `file_results`/the summary with zero semantic comments — they aren't dropped from the PR, just not sent to Claude.
  - **Don't enable all three skip/filter controls at once — they compound and starve the review.** `RISKY_FILES_ONLY` skips most files, `TWO_PASS_MODE` skips whatever's left with no static hit (note the `elif` at `pipeline.py:143-146`: a *risky* file with no Ruff/ESLint finding is skipped too), and `ONLY_CRITICAL_SEVERITY` silences the few that reach Claude unless there's a 🔴. Combined, most PRs come back as `"✅ No se encontraron problemas"`. **Recommended balanced combo (low cost, reviews still show content): `ONLY_CRITICAL_SEVERITY=false`, `TWO_PASS_MODE=false`, `RISKY_FILES_ONLY=true`** — one cost lever (deep review only on risky/large files), full 🔴🟡🔵 output on those. To review *every* file cheaply instead, set `RISKY_FILES_ONLY=false` and lower `MAX_PATCH_CHARS` (e.g. 8000) — costs more on big PRs (one call per file) but nothing goes unreviewed.

## Environment variables

`GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, one of `GITHUB_APP_PRIVATE_KEY` / `GITHUB_APP_PRIVATE_KEY_PATH`, and an API key for whichever provider is active (`ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`). `PORT` defaults to 8000. `LLM_PROVIDER` selects the semantic-analysis backend: `anthropic` (default) or `openai`. Optional cost knobs: `ANTHROPIC_MODEL` (defaults to `claude-haiku-4-5`), `OPENAI_MODEL` (defaults to `gpt-4o-mini`), `MAX_PATCH_CHARS` (defaults to 12000), `MAX_INLINE_COMMENTS` (defaults to 15), `ONLY_CRITICAL_SEVERITY`, `TWO_PASS_MODE`, `RISKY_FILES_ONLY` + `RISKY_FILE_PATTERNS` + `RISKY_PATCH_SIZE` (all default off — see cost controls above). Optional observability: `OBSERVATORY_TOKEN` (`obs_sk_...`; enables `llm-observatory` metrics for either provider) and `OBSERVATORY_URL` (defaults to the Railway instance). See `.env.example`. Supported file extensions live in `config/settings.py` (`.py`, `.js`, `.ts`, `.jsx`, `.tsx`).
