from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from config.settings import CLONE_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


def clone_pr_repo(repo: str, head_sha: str, token: str) -> str | None:
    """
    Clona el repo exactamente en el SHA del PR (no en la rama — la rama pudo
    haber avanzado desde que se disparó el webhook). Usa fetch --depth 1 al
    SHA en vez de `git clone --branch` por eso mismo.

    Devuelve la ruta al working tree clonado, o None si falla por cualquier
    motivo (git no instalado, timeout, permisos, red) — nunca debe tumbar
    el pipeline; el caller cae al fallback de Contents API.
    """
    repo_dir = tempfile.mkdtemp(prefix="pr-")
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    steps = [
        ["git", "init", "-q", repo_dir],
        ["git", "-C", repo_dir, "remote", "add", "origin", remote_url],
        ["git", "-C", repo_dir, "fetch", "--depth", "1", "origin", head_sha],
        ["git", "-C", repo_dir, "checkout", "-q", "FETCH_HEAD"],
    ]

    try:
        for step in steps:
            subprocess.run(
                step,
                capture_output=True,
                text=True,
                timeout=CLONE_TIMEOUT_SECONDS,
                check=True,
            )
        logger.info(f"Repo clonado: {repo}@{head_sha[:8]} → {repo_dir}")
        return repo_dir
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout clonando {repo}@{head_sha[:8]} (>{CLONE_TIMEOUT_SECONDS}s)")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Error clonando {repo}@{head_sha[:8]}: {e.stderr.strip()}")
    except FileNotFoundError:
        logger.warning("git no encontrado — saltando clonado de repo")
    except Exception as e:
        logger.warning(f"Error inesperado clonando {repo}@{head_sha[:8]}: {e}")

    cleanup_repo(repo_dir)
    return None


def cleanup_repo(repo_path: str | None) -> None:
    if repo_path:
        shutil.rmtree(repo_path, ignore_errors=True)


def read_file(repo_path: str, filename: str) -> str | None:
    """Lee un archivo del working tree clonado. None si no existe o no es legible."""
    try:
        path = Path(repo_path) / filename
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Error leyendo {filename} del clon: {e}")
        return None
