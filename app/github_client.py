from __future__ import annotations

import logging
import time
import jwt
import httpx
from config.settings import GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _generate_jwt() -> str:
    """Genera un JWT firmado con la private key de la GitHub App."""
    with open(GITHUB_APP_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": GITHUB_APP_ID,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(installation_id: int) -> str:
    """Obtiene un token de acceso para la instalación específica."""
    app_jwt = _generate_jwt()
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"

    with httpx.Client() as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()["token"]


def get_pr_files(repo: str, pr_number: int, token: str) -> list[dict]:
    """Retorna la lista de archivos modificados en el PR."""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"

    with httpx.Client() as client:
        resp = client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def post_review(
    repo: str,
    pr_number: int,
    token: str,
    body: str,
    comments: list[dict],
) -> None:
    """
    Publica un review con comentarios inline en el PR.
    comments: [{"path": str, "line": int, "body": str}]
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews"

    payload = {
        "body": body,
        "event": "COMMENT",
        "comments": comments,
    }

    with httpx.Client() as client:
        resp = client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        logger.info(f"Review publicado en {repo}#{pr_number} con {len(comments)} comentarios")
