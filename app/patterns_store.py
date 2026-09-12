from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from app.github_client import (
    get_file_with_sha,
    get_installation_token,
    list_commits_for_path,
    update_file,
)
from config.settings import GITHUB_INSTALLATION_ID, SELF_REPO

logger = logging.getLogger(__name__)

# Ruta tal como aparece en el repo (usada tanto para leer/escribir local como
# para la Contents API) — mismo archivo, dos formas de acceso.
PATTERNS_REPO_PATH = "config/false_positives.json"
_LOCAL_PATH = Path(__file__).resolve().parent.parent / PATTERNS_REPO_PATH


def load_local() -> list[dict]:
    """
    Lee config/false_positives.json del filesystem del proceso — es lo que
    usa semantic_analyzer.py en cada request, sin llamar a GitHub.
    Si el archivo falta o está corrupto, degrada a lista vacía (nunca debe
    tumbar el análisis semántico por esto).
    """
    try:
        return json.loads(_LOCAL_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"No se pudo leer {PATTERNS_REPO_PATH}: {e}")
        return []


def as_prompt_texts(patterns: list[dict]) -> list[str]:
    return [p["text"] for p in patterns if p.get("text")]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "patron"


def _self_token() -> str:
    return get_installation_token(GITHUB_INSTALLATION_ID)


def _load_from_github(token: str) -> tuple[list[dict], str]:
    result = get_file_with_sha(SELF_REPO, PATTERNS_REPO_PATH, "main", token)
    if result is None:
        raise RuntimeError(f"No se pudo leer {PATTERNS_REPO_PATH} desde {SELF_REPO}@main")
    content, sha = result
    return json.loads(content), sha


def _sync_local(patterns: list[dict]) -> None:
    """Refleja el estado recién commiteado en el archivo local, para que este
    mismo proceso lo use ya sin esperar al redeploy que dispara el push."""
    _LOCAL_PATH.write_text(
        json.dumps(patterns, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def add_pattern(text: str, source: str = "") -> dict:
    """
    Agrega un patrón: lee el archivo actual desde GitHub (fuente de verdad,
    evita pisar un cambio hecho por otro lado), le suma la entrada nueva, y
    commitea directo a main. El push dispara el redeploy normal de Railway.
    """
    token = _self_token()
    patterns, sha = _load_from_github(token)

    existing_ids = {p["id"] for p in patterns}
    base_id = _slugify(text)
    new_id = base_id
    n = 2
    while new_id in existing_ids:
        new_id = f"{base_id}-{n}"
        n += 1

    entry = {
        "id": new_id,
        "text": text,
        "source": source,
        "added_at": date.today().isoformat(),
    }
    patterns.append(entry)

    update_file(
        SELF_REPO,
        PATTERNS_REPO_PATH,
        json.dumps(patterns, ensure_ascii=False, indent=2) + "\n",
        sha,
        message=f"patrones: agregar '{new_id}'",
        token=token,
    )
    _sync_local(patterns)
    return entry


def remove_pattern(pattern_id: str) -> bool:
    """Quita un patrón por id. Retorna False si no existía."""
    token = _self_token()
    patterns, sha = _load_from_github(token)

    filtered = [p for p in patterns if p["id"] != pattern_id]
    if len(filtered) == len(patterns):
        return False

    update_file(
        SELF_REPO,
        PATTERNS_REPO_PATH,
        json.dumps(filtered, ensure_ascii=False, indent=2) + "\n",
        sha,
        message=f"patrones: quitar '{pattern_id}'",
        token=token,
    )
    _sync_local(filtered)
    return True


def fetch_history(limit: int = 15) -> list[dict]:
    """Historial de commits que tocaron el archivo de patrones, para el panel."""
    token = _self_token()
    commits = list_commits_for_path(SELF_REPO, PATTERNS_REPO_PATH, token, per_page=limit)
    return [
        {
            "sha": c["sha"][:7],
            "message": c["commit"]["message"].splitlines()[0],
            "date": c["commit"]["author"]["date"],
            "url": c["html_url"],
        }
        for c in commits
    ]
