from __future__ import annotations

import hashlib
import hmac
import json
import logging
from config.settings import GITHUB_WEBHOOK_SECRET

logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Verifica la firma HMAC del webhook de GitHub."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET no configurado — saltando verificación")
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature_header)


def parse_pr_event(payload: dict) -> dict | None:
    """
    Extrae los datos relevantes del evento pull_request.
    Retorna None si el evento no debe procesarse.
    """
    action = payload.get("action")
    if action not in ("opened", "synchronize"):
        logger.info(f"Acción ignorada: {action}")
        return None

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    installation = payload.get("installation", {})

    return {
        "action": action,
        "pr_number": pr.get("number"),
        "pr_title": pr.get("title"),
        "head_sha": pr.get("head", {}).get("sha"),
        "base_sha": pr.get("base", {}).get("sha"),
        "repo_full_name": repo.get("full_name"),
        "installation_id": installation.get("id"),
    }
