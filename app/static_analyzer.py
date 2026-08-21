from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import os

logger = logging.getLogger(__name__)


def analyze_python(code: str, filename: str, file_path: str | None = None) -> list[dict]:
    """
    Corre ruff sobre el archivo Python. Si file_path apunta a un archivo real
    dentro de un repo clonado, lo analiza ahí mismo (imports y pyproject.toml
    reales se resuelven). Si no, cae al modo aislado: escribe `code` (hoy,
    solo las líneas '+' del diff) a un temp file sin contexto del proyecto.
    Retorna lista de {line, message, code}.
    """
    tmp_path = None
    target_path = file_path
    if target_path is None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        target_path = tmp_path

    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", target_path],
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
        if tmp_path:
            os.unlink(tmp_path)


def analyze_javascript(code: str, filename: str, file_path: str | None = None) -> list[dict]:
    """
    Corre eslint sobre el archivo JS/TS. Con file_path (repo clonado) usa el
    .eslintrc real del proyecto; en modo aislado fuerza --no-eslintrc y un
    entorno genérico porque no hay config del proyecto disponible.
    Retorna lista de {line, message, rule}.
    """
    tmp_path = None
    target_path = file_path

    if target_path is None:
        ext = os.path.splitext(filename)[1] or ".js"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        target_path = tmp_path

    cmd = ["eslint", "--format=json"]
    if tmp_path:
        cmd += ["--no-eslintrc", "--env=es2021,node"]
    cmd.append(target_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
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
        if tmp_path:
            os.unlink(tmp_path)


def run_static_analysis(
    language: str, code: str, filename: str, file_path: str | None = None
) -> list[dict]:
    if language == "python":
        return analyze_python(code, filename, file_path)
    elif language in ("javascript", "typescript"):
        return analyze_javascript(code, filename, file_path)
    return []
