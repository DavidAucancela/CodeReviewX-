from __future__ import annotations

import logging

from app.github_client import (
    get_app_slug,
    get_installation_token,
    list_installation_repos,
    list_pr_review_comments,
    list_pr_reviews,
    list_pull_requests,
)
from config.settings import GITHUB_INSTALLATION_ID

logger = logging.getLogger(__name__)

_SEVERITY_EMOJIS = ("🔴", "🟡", "🔵")

# El slug de la App no cambia en caliente — se cachea tras la primera consulta
# para no gastar una llamada extra a /app en cada refresh del dashboard.
_bot_login_cache: str | None = None


def _bot_login() -> str:
    global _bot_login_cache
    if _bot_login_cache is None:
        _bot_login_cache = f"{get_app_slug()}[bot]"
    return _bot_login_cache


def _severity_counts(bodies: list[str]) -> dict:
    counts = {emoji: 0 for emoji in _SEVERITY_EMOJIS}
    for body in bodies:
        for emoji in _SEVERITY_EMOJIS:
            if emoji in body:
                counts[emoji] += 1
                break
    return counts


def list_repos() -> list[str]:
    """Repos donde el bot está instalado, para el selector del dashboard."""
    token = get_installation_token(GITHUB_INSTALLATION_ID)
    repos = list_installation_repos(token)
    return sorted(r["full_name"] for r in repos)


def list_reviewed_prs(repo: str, limit: int = 15) -> list[dict]:
    """
    PRs recientes de `repo` en los que el bot dejó un review, con sus
    comentarios inline. Todo se lee en vivo de la API de GitHub — nada se
    persiste localmente, así que no hay costo ni archivos saltados por los
    cost controls (eso no queda registrado en ningún lado todavía).
    """
    token = get_installation_token(GITHUB_INSTALLATION_ID)
    bot_login = _bot_login()
    prs = list_pull_requests(repo, token, state="all", per_page=limit)

    reviewed = []
    for pr in prs:
        number = pr["number"]
        reviews = list_pr_reviews(repo, number, token)
        bot_reviews = [r for r in reviews if (r.get("user") or {}).get("login") == bot_login]
        if not bot_reviews:
            continue

        comments = list_pr_review_comments(repo, number, token)
        bot_comments = [c for c in comments if (c.get("user") or {}).get("login") == bot_login]

        reviewed.append({
            "number": number,
            "title": pr["title"],
            "url": pr["html_url"],
            "state": pr["state"],
            "author": (pr.get("user") or {}).get("login"),
            "updated_at": pr["updated_at"],
            "review_body": bot_reviews[-1].get("body", ""),
            "severity_counts": _severity_counts([c["body"] for c in bot_comments]),
            "comments": [
                {
                    "path": c["path"],
                    "line": c.get("line") or c.get("original_line"),
                    "body": c["body"],
                    "url": c["html_url"],
                }
                for c in bot_comments
            ],
        })

    return reviewed
