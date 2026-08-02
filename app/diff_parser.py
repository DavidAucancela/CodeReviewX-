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


def _iter_patch_lines(patch: str):
    """
    Recorre un patch de GitHub línea por línea, calculando para cada una su
    número de línea real en el archivo nuevo (None si no aplica: headers @@ o
    líneas eliminadas) y su posición absoluta en el patch (para la API de
    comentarios de GitHub). Compartido por parse_diff_lines y annotate_patch
    para que ambos usen exactamente el mismo conteo de hunks.
    """
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
            yield raw_line, None, position
            continue

        if raw_line.startswith("-"):
            # Línea eliminada — no tiene número en el archivo nuevo
            yield raw_line, None, position
            continue

        current_line += 1
        yield raw_line, current_line, position


def parse_diff_lines(patch: str) -> dict[int, int]:
    """
    Convierte el patch de GitHub en un mapa {line_number: diff_position}.
    diff_position es lo que necesita la API de GitHub para comentarios inline.
    """
    if not patch:
        return {}

    line_map = {}

    for raw_line, real_line, position in _iter_patch_lines(patch):
        if real_line is not None and raw_line.startswith("+"):
            # Línea agregada — es la que podemos comentar
            line_map[real_line] = position

    return line_map


def annotate_patch(patch: str) -> str:
    """
    Reescribe el patch prefijando cada línea con su número de línea real en el
    archivo nuevo (en blanco para headers @@ y líneas eliminadas, que no
    tienen número en el archivo nuevo).

    El LLM recibe este texto en vez del patch crudo para que copie el número
    de línea en lugar de tener que contarlo manualmente desde los headers
    @@ -a,b +c,d @@ — modelos distintos infieren ese conteo con distinta
    fiabilidad, y un desajuste hace que _build_inline_comments descarte el
    comentario en silencio (su línea nunca cae en line_map).
    """
    if not patch:
        return patch

    out = []
    for raw_line, real_line, _ in _iter_patch_lines(patch):
        prefix = f"{real_line:>5} " if real_line is not None else "      "
        out.append(prefix + raw_line)

    return "\n".join(out)


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
