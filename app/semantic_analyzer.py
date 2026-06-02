from __future__ import annotations

import json
import logging
import anthropic
from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Eres un revisor de código senior con experiencia en Python y JavaScript.
Tu trabajo es detectar problemas reales en diffs de PRs — no trivialidades de estilo.

Responde SIEMPRE con un array JSON válido. Sin texto adicional.
Si no hay problemas, responde: []
"""

USER_PROMPT_TEMPLATE = """Archivo: {filename}
Lenguaje: {language}

Issues detectados por análisis estático:
{static_issues}

Diff del PR:
```
{patch}
```

Identifica problemas en las líneas NUEVAS (líneas con +) del diff:
1. Bugs lógicos o edge cases no manejados
2. Código que puede fallar en producción (null refs, excepciones no capturadas, async mal usado)
3. Problemas de seguridad (inyección, secrets expuestos, validación ausente)
4. Lógica confusa que indica un posible error de diseño

Responde con array JSON:
[{{"line": <número de línea en el archivo>, "comment": "<explicación concisa en español>"}}]

Solo incluye problemas concretos y accionables. Máximo 5 comentarios por archivo."""


def analyze_semantically(
    filename: str,
    language: str,
    patch: str,
    static_issues: list[dict],
) -> list[dict]:
    """
    Analiza el diff con Claude y retorna lista de {line, comment}.
    """
    if not patch:
        return []

    static_summary = (
        "\n".join(f"  - Línea {i['line']}: {i['message']}" for i in static_issues)
        if static_issues
        else "  Ninguno"
    )

    prompt = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        language=language,
        static_issues=static_summary,
        patch=patch,
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()

        # Limpia posibles bloques de código markdown
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        comments = json.loads(raw)
        return [c for c in comments if isinstance(c, dict) and "line" in c and "comment" in c]

    except json.JSONDecodeError as e:
        logger.error(f"Claude no retornó JSON válido: {e}")
        return []
    except Exception as e:
        logger.error(f"Error en análisis semántico: {e}")
        return []
