from __future__ import annotations

import logging
from app.github_client import get_installation_token, get_pr_files, post_review
from app.diff_parser import extract_file_contexts
from app.static_analyzer import run_static_analysis
from app.semantic_analyzer import analyze_semantically
from config.settings import (
    MAX_INLINE_COMMENTS,
    TWO_PASS_MODE,
    RISKY_FILES_ONLY,
    RISKY_FILE_PATTERNS,
    RISKY_PATCH_SIZE,
)

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"🔴": 0, "🟡": 1, "🔵": 2}


def _severity(body: str) -> int:
    for emoji, rank in _SEVERITY_RANK.items():
        if emoji in body:
            return rank
    return 3


def _is_risky_file(filename: str, new_code_lines: list[str]) -> bool:
    """Heurística para RISKY_FILES_ONLY: nombre sensible o diff grande."""
    if len(new_code_lines) > RISKY_PATCH_SIZE:
        return True
    lower_name = filename.lower()
    return any(pattern in lower_name for pattern in RISKY_FILE_PATTERNS)


def _build_inline_comments(file_ctx: dict, semantic_comments: list[dict]) -> list[dict]:
    """
    Convierte comentarios {line, comment} en el formato que espera la GitHub API.
    Solo incluye comentarios cuya línea esté en el diff (line_map).
    """
    line_map = file_ctx["line_map"]
    inline = []

    for c in semantic_comments:
        line = c.get("line")
        if line and line in line_map:
            inline.append({
                "path": file_ctx["filename"],
                "line": line,
                "side": "RIGHT",
                "body": f"🤖 **Code Review IA**\n\n{c['comment']}",
                "_severity": _severity(c["comment"]),
            })

    return inline


def _build_summary(
    file_results: list[tuple[dict, list[dict]]],
    total_inline: int,
    posted_inline: int,
) -> str:
    total_findings = sum(len(comments) for _, comments in file_results)

    if total_findings == 0:
        return "✅ Revisión completada. No se encontraron problemas significativos."

    header_parts = [
        "🔍 **Revisión automática completada**\n\n",
        f"Se analizaron **{len(file_results)}** archivo(s) con cambios. "
        f"Claude detectó **{total_findings}** observación(es).",
    ]

    if total_inline > posted_inline:
        header_parts.append(
            f" Se muestran las **{posted_inline}** más críticas como comentarios inline; "
            f"las restantes **{total_inline - posted_inline}** aparecen solo en este resumen."
        )

    header_parts.append("\n\n---\n\n### Hallazgos por archivo\n")

    file_sections = []
    for ctx, comments in file_results:
        if not comments:
            continue
        filename = ctx["filename"]
        lines = [f"\n**`{filename}`** — {len(comments)} observación(es)\n"]
        for c in comments:
            first_line = c["comment"].split("\n")[0]
            lines.append(f"- Línea {c.get('line', '?')}: {first_line}\n")
        file_sections.append("".join(lines))

    return "".join(header_parts) + "".join(file_sections)


def run_review_pipeline(
    repo: str,
    pr_number: int,
    installation_id: int,
) -> None:
    """Pipeline completo: obtiene diff → analiza → publica comentarios.

    Corre en un hilo de fondo, así que cualquier excepción se loguea aquí:
    de lo contrario desaparecería sin rastro (el webhook ya respondió 200).
    """
    try:
        _run_review_pipeline(repo, pr_number, installation_id)
    except Exception:
        logger.exception(f"Pipeline falló para {repo}#{pr_number}")


def _run_review_pipeline(
    repo: str,
    pr_number: int,
    installation_id: int,
) -> None:
    logger.info(f"Iniciando review: {repo}#{pr_number}")

    token = get_installation_token(installation_id)
    pr_files = get_pr_files(repo, pr_number, token)
    file_contexts = extract_file_contexts(pr_files)

    if not file_contexts:
        logger.info("No hay archivos soportados en el PR — nada que revisar")
        return

    # Acumula (ctx, semantic_comments) y todos los candidatos a inline
    file_results: list[tuple[dict, list[dict]]] = []
    all_inline: list[dict] = []

    for ctx in file_contexts:
        logger.info(f"Analizando {ctx['filename']} ({ctx['language']})")

        new_code_lines = [
            line[1:] for line in ctx["patch"].splitlines() if line.startswith("+")
        ]
        new_code = "\n".join(new_code_lines)

        static_issues = run_static_analysis(ctx["language"], new_code, ctx["filename"])
        logger.info(f"  → {len(static_issues)} issues estáticos")

        skip_reason = None
        if RISKY_FILES_ONLY and not _is_risky_file(ctx["filename"], new_code_lines):
            skip_reason = "archivo no riesgoso (RISKY_FILES_ONLY)"
        elif TWO_PASS_MODE and not static_issues:
            skip_reason = "sin issues estáticos (TWO_PASS_MODE)"

        if skip_reason:
            logger.info(f"  → análisis semántico omitido: {skip_reason}")
            semantic_comments = []
        else:
            semantic_comments = analyze_semantically(
                filename=ctx["filename"],
                language=ctx["language"],
                patch=ctx["patch"],
                static_issues=static_issues,
            )
            logger.info(f"  → {len(semantic_comments)} comentarios semánticos")

        inline = _build_inline_comments(ctx, semantic_comments)
        all_inline.extend(inline)
        file_results.append((ctx, semantic_comments))

    # Ordena por severidad y aplica el cap global
    all_inline.sort(key=lambda c: c["_severity"])
    posted_inline = all_inline[:MAX_INLINE_COMMENTS]
    # Elimina el campo interno antes de enviar a GitHub
    for c in posted_inline:
        c.pop("_severity", None)

    logger.info(
        f"Comentarios inline: {len(all_inline)} generados → {len(posted_inline)} publicados "
        f"(cap={MAX_INLINE_COMMENTS})"
    )

    summary = _build_summary(file_results, len(all_inline), len(posted_inline))

    post_review(
        repo=repo,
        pr_number=pr_number,
        token=token,
        body=summary,
        comments=posted_inline,
    )

    logger.info(f"Review completado: {len(posted_inline)} inline + resumen publicado")
