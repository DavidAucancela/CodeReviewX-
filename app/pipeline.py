from __future__ import annotations

import logging
from app.github_client import get_installation_token, get_pr_files, post_review
from app.diff_parser import extract_file_contexts
from app.static_analyzer import run_static_analysis
from app.semantic_analyzer import analyze_semantically

logger = logging.getLogger(__name__)


def _build_inline_comments(file_ctx: dict, semantic_comments: list[dict]) -> list[dict]:
    """
    Convierte comentarios {line, comment} en el formato que espera la GitHub API:
    {path, line, body, side}
    Solo incluye comentarios cuya línea esté en el diff.
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
            })

    return inline


def run_review_pipeline(
    repo: str,
    pr_number: int,
    installation_id: int,
) -> None:
    """Pipeline completo: obtiene diff → analiza → publica comentarios."""
    logger.info(f"Iniciando review: {repo}#{pr_number}")

    token = get_installation_token(installation_id)
    pr_files = get_pr_files(repo, pr_number, token)
    file_contexts = extract_file_contexts(pr_files)

    if not file_contexts:
        logger.info("No hay archivos soportados en el PR — nada que revisar")
        return

    all_inline_comments = []

    for ctx in file_contexts:
        logger.info(f"Analizando {ctx['filename']} ({ctx['language']})")

        # Extraer el código nuevo del patch para análisis estático
        new_code_lines = [
            line[1:] for line in ctx["patch"].splitlines() if line.startswith("+")
        ]
        new_code = "\n".join(new_code_lines)

        static_issues = run_static_analysis(ctx["language"], new_code, ctx["filename"])
        logger.info(f"  → {len(static_issues)} issues estáticos")

        semantic_comments = analyze_semantically(
            filename=ctx["filename"],
            language=ctx["language"],
            patch=ctx["patch"],
            static_issues=static_issues,
        )
        logger.info(f"  → {len(semantic_comments)} comentarios semánticos")

        inline = _build_inline_comments(ctx, semantic_comments)
        all_inline_comments.extend(inline)

    if not all_inline_comments:
        summary = "✅ Revisión completada. No se encontraron problemas significativos."
    else:
        summary = (
            f"🔍 **Revisión automática completada**\n\n"
            f"Se encontraron **{len(all_inline_comments)}** observaciones "
            f"en {len(file_contexts)} archivo(s)."
        )

    post_review(
        repo=repo,
        pr_number=pr_number,
        token=token,
        body=summary,
        comments=all_inline_comments,
    )

    logger.info(f"Review completado: {len(all_inline_comments)} comentarios publicados")
