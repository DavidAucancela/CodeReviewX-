from __future__ import annotations

import os
from config.settings import SUPPORTED_EXTENSIONS


def filter_supported_files(pr_files: list[dict]) -> list[dict]:
    """Filtra archivos con extensiones soportadas que no fueron eliminados."""
    result = []
    for f in pr_files:
        filename = f.get("filename", "")
        status = f.get("status", "")
        _, ext = os.path.splitext(filename)

        if ext in SUPPORTED_EXTENSIONS and status != "removed":
            result.append(f)
    return result


def parse_diff_lines(patch: str) -> dict[int, int]:
    """
    Convierte el patch de GitHub en un mapa {line_number: diff_position}.
    diff_position es lo que necesita la API de GitHub para comentarios inline.
    """
    if not patch:
        return {}

    line_map = {}
    current_line = 0
    position = 0

    for raw_line in patch.splitlines():
        position += 1

        if raw_line.startswith("@@"):
            # Extrae el número de línea de destino: @@ -a,b +c,d @@
            try:
                after = raw_line.split("+")[1].split("@@")[0].strip()
                current_line = int(after.split(",")[0]) - 1
            except (IndexError, ValueError):
                pass
            continue

        if raw_line.startswith("-"):
            # Línea eliminada — no tiene número en el archivo nuevo
            continue

        current_line += 1

        if raw_line.startswith("+"):
            # Línea agregada — es la que podemos comentar
            line_map[current_line] = position

    return line_map


def extract_file_contexts(pr_files: list[dict]) -> list[dict]:
    """
    Retorna lista de contextos por archivo listos para análisis.
    Cada item: {filename, language, patch, line_map}
    """
    supported = filter_supported_files(pr_files)
    contexts = []

    for f in supported:
        filename = f.get("filename", "")
        patch = f.get("patch", "")
        _, ext = os.path.splitext(filename)

        language = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
        }.get(ext, "unknown")

        line_map = parse_diff_lines(patch)

        contexts.append({
            "filename": filename,
            "language": language,
            "patch": patch,
            "line_map": line_map,
        })

    return contexts
