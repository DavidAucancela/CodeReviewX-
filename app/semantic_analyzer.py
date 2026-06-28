from __future__ import annotations

import json
import logging
import anthropic
from config.settings import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, MAX_PATCH_CHARS

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Eres un revisor de código senior que escribe para un equipo
con desarrolladores junior y semi-senior. Detectas problemas REALES en diffs de
PRs (bugs, fallos en producción, seguridad, lógica confusa) — nunca trivialidades
de estilo.

Tu prioridad es que CUALQUIER desarrollador entienda el comentario en 10 segundos.

Reglas de redacción (OBLIGATORIAS):
- Empieza por el IMPACTO, no por el detalle técnico. Di qué se rompe para el
  usuario o el sistema antes de explicar el código.
- Frases cortas. Una idea por frase. Máximo ~3 frases por comentario.
- Evita la jerga. Si usas un nombre de variable o función, explícalo en palabras
  ("la marca de 'ya se intentó'", no solo "autoTriedRef").
- Nada de "promesa en vuelo", "default del switch", etc. Usa lenguaje natural.
- Tono colaborador, no de examen.

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

Para CADA problema, escribe el campo "comment" con esta estructura exacta
(usa saltos de línea reales entre las partes):

{{severidad}} **Qué pasa:** <en 1 frase, el impacto en lenguaje claro>
**Por qué importa:** <la consecuencia concreta>
**Sugerencia:** <una acción accionable>

Donde {{severidad}} es uno de: 🔴 (alta), 🟡 (media), 🔵 (baja).

Responde con array JSON:
[{{"line": <número de línea en el archivo>, "comment": "<comentario con la estructura de arriba>"}}]

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

    # Acota diffs enormes para controlar el costo (ver MAX_PATCH_CHARS).
    if len(patch) > MAX_PATCH_CHARS:
        logger.info(
            f"  Diff de {filename} truncado: {len(patch)} → {MAX_PATCH_CHARS} chars"
        )
        patch = patch[:MAX_PATCH_CHARS] + "\n... (diff truncado por longitud)"

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
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        # Loguea consumo de tokens para medir el costo real por archivo.
        usage = message.usage
        logger.info(
            f"  Tokens [{ANTHROPIC_MODEL}] entrada={usage.input_tokens} "
            f"salida={usage.output_tokens}"
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
