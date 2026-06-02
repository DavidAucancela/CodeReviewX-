from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import os

logger = logging.getLogger(__name__)


def analyze_python(code: str, filename: str) -> list[dict]:
    """
    Corre ruff sobre el contenido del archivo Python.
    Retorna lista de {line, message, code}.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", tmp_path],
            capture_output=True,
            text=True,
        )
        issues = []
        if result.stdout:
            raw = json.loads(result.stdout)
            for item in raw:
                issues.append({
                    "line": item.get("location", {}).get("row", 0),
                    "code": item.get("code", ""),
                    "message": item.get("message", ""),
                })
        return issues
    except FileNotFoundError:
        logger.warning("ruff no encontrado — saltando análisis estático Python")
        return []
    except Exception as e:
        logger.error(f"Error en análisis Python: {e}")
        return []
    finally:
        os.unlink(tmp_path)


def analyze_javascript(code: str, filename: str) -> list[dict]:
    """
    Corre eslint sobre el contenido JS/TS.
    Retorna lista de {line, message, rule}.
    """
    ext = os.path.splitext(filename)[1] or ".js"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=ext, delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["eslint", "--format=json", "--no-eslintrc", "--env=es2021,node", tmp_path],
            capture_output=True,
            text=True,
        )
        issues = []
        if result.stdout:
            raw = json.loads(result.stdout)
            for file_result in raw:
                for msg in file_result.get("messages", []):
                    issues.append({
                        "line": msg.get("line", 0),
                        "rule": msg.get("ruleId", ""),
                        "message": msg.get("message", ""),
                    })
        return issues
    except FileNotFoundError:
        logger.warning("eslint no encontrado — saltando análisis estático JS")
        return []
    except Exception as e:
        logger.error(f"Error en análisis JS: {e}")
        return []
    finally:
        os.unlink(tmp_path)


def run_static_analysis(language: str, code: str, filename: str) -> list[dict]:
    if language == "python":
        return analyze_python(code, filename)
    elif language in ("javascript", "typescript"):
        return analyze_javascript(code, filename)
    return []
