from __future__ import annotations

import json
import logging
import anthropic
import openai
from app.diff_parser import annotate_patch
from config.settings import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_PROVIDER,
    MAX_FILE_CONTEXT_CHARS,
    MAX_PATCH_CHARS,
    ONLY_CRITICAL_SEVERITY,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OBSERVATORY_URL,
    OBSERVATORY_TOKEN,
)

logger = logging.getLogger(__name__)

MODEL = OPENAI_MODEL if LLM_PROVIDER == "openai" else ANTHROPIC_MODEL


def _build_client():
    """Crea el cliente de Claude u OpenAI según LLM_PROVIDER.

    Con OBSERVATORY_TOKEN, envuelve el cliente con llm-observatory para enviar
    métricas de uso/costo (soporta ambos proveedores). Si el SDK no está
    instalado o falla al inicializar (p. ej. Python < 3.10, URL/token
    inválidos), cae al cliente plano correspondiente: la observabilidad nunca
    debe impedir que el bot revise PRs.
    """
    token = OBSERVATORY_TOKEN.strip() if OBSERVATORY_TOKEN else ""

    if LLM_PROVIDER == "openai":
        if not token:
            logger.info("LLM Observatory desactivado (sin OBSERVATORY_TOKEN); no se envían métricas")
            return openai.OpenAI(api_key=OPENAI_API_KEY)
        try:
            from llm_observatory import MonitoredOpenAI

            client = MonitoredOpenAI(
                api_key=OPENAI_API_KEY,
                observatory_url=OBSERVATORY_URL,
                observatory_token=token,
                tags={"app": "codereviewx", "env": "production"},
            )
            logger.info(f"LLM Observatory activado (OpenAI); métricas hacia {OBSERVATORY_URL}")
            return client
        except Exception as e:
            logger.error(
                f"No se pudo inicializar LLM Observatory ({type(e).__name__}: {e}); "
                "se usa el cliente OpenAI sin métricas"
            )
            return openai.OpenAI(api_key=OPENAI_API_KEY)

    if not token:
        logger.info("LLM Observatory desactivado (sin OBSERVATORY_TOKEN); no se envían métricas")
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        from llm_observatory import MonitoredAnthropic

        client = MonitoredAnthropic(
            api_key=ANTHROPIC_API_KEY,
            observatory_url=OBSERVATORY_URL,
            observatory_token=token,
            tags={"app": "codereviewx", "env": "production"},
        )
        logger.info(f"LLM Observatory activado; métricas hacia {OBSERVATORY_URL}")
        return client
    except Exception as e:
        logger.error(
            f"No se pudo inicializar LLM Observatory ({type(e).__name__}: {e}); "
            "se usa el cliente Anthropic sin métricas"
        )
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


client = _build_client()
logger.info(f"Proveedor de análisis semántico: {LLM_PROVIDER} (modelo={MODEL})")

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
{full_file_section}
Diff del PR (cada línea está precedida por su número de línea real en el
archivo nuevo; en blanco para headers `@@` y líneas eliminadas, que no tienen
número en el archivo nuevo):
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

{severity_filter}

Responde con array JSON:
[{{"line": <copia EXACTAMENTE el número que precede a esa línea en el diff de arriba — no lo cuentes vos>, "comment": "<comentario con la estructura de arriba>"}}]

Solo incluye problemas concretos y accionables. Máximo 5 comentarios por archivo."""

_FULL_FILE_SECTION_TEMPLATE = """
Archivo completo (para contexto — NO reportes problemas de código
preexistente que no forme parte del diff de arriba; úsalo solo para
entender qué hacen las funciones/variables/clases que el diff referencia):
```
{full_file}
```
"""

_CRITICAL_ONLY_INSTRUCTION = (
    "IMPORTANTE: Reporta ÚNICAMENTE problemas de severidad 🔴 (alta): "
    "vulnerabilidades de seguridad, crashes, lógica rota que causa fallos en "
    "producción. NO reportes nada de severidad 🟡 o 🔵 (estilo, performance "
    "menor, legibilidad, mejoras opcionales). Si no hay problemas graves, "
    "responde []."
)


def analyze_semantically(
    filename: str,
    language: str,
    patch: str,
    static_issues: list[dict],
    full_file: str | None = None,
) -> list[dict]:
    """
    Analiza el diff con el LLM configurado (LLM_PROVIDER) y retorna lista de {line, comment}.
    full_file (opcional): contenido completo del archivo, usado solo como
    contexto para resolver símbolos/funciones fuera del hunk visible.
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

    full_file_section = ""
    if full_file:
        if len(full_file) > MAX_FILE_CONTEXT_CHARS:
            full_file = full_file[:MAX_FILE_CONTEXT_CHARS] + "\n... (archivo truncado por longitud)"
        full_file_section = _FULL_FILE_SECTION_TEMPLATE.format(full_file=full_file)

    prompt = USER_PROMPT_TEMPLATE.format(
        filename=filename,
        language=language,
        static_issues=static_summary,
        full_file_section=full_file_section,
        patch=annotate_patch(patch),
        severity_filter=_CRITICAL_ONLY_INSTRUCTION if ONLY_CRITICAL_SEVERITY else "",
    )

    try:
        if LLM_PROVIDER == "openai":
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            usage = response.usage
            logger.info(
                f"  Tokens [{MODEL}] entrada={usage.prompt_tokens} "
                f"salida={usage.completion_tokens}"
            )
            raw = response.choices[0].message.content.strip()
        else:
            message = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Loguea consumo de tokens para medir el costo real por archivo.
            usage = message.usage
            logger.info(
                f"  Tokens [{MODEL}] entrada={usage.input_tokens} "
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
        logger.error(f"El modelo no retornó JSON válido: {e}")
        return []
    except Exception as e:
        logger.error(f"Error en análisis semántico: {e}")
        return []
