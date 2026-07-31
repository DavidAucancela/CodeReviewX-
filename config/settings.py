import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 8000))

# Qué proveedor usa el análisis semántico. "anthropic" (default) o "openai" —
# útil para seguir revisando PRs si se agota el crédito de una de las dos cuentas.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()

# Modelo de Claude para el análisis semántico. Haiku 4.5 es ~3x más barato que
# Sonnet 4.6 ($1/$5 vs $3/$15 por 1M tokens). Para máxima detección de bugs,
# poner ANTHROPIC_MODEL=claude-sonnet-4-6 en el entorno.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

# Modelo de OpenAI para el análisis semántico (solo si LLM_PROVIDER=openai).
# gpt-4o-mini es el equivalente en costo/calidad a Haiku 4.5.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Tope de caracteres del diff que se envía a Claude por archivo. Evita que un
# archivo enorme dispare el costo (~4 chars/token → 12000 chars ≈ 3000 tokens).
MAX_PATCH_CHARS = int(os.getenv("MAX_PATCH_CHARS", 12000))

# Máximo de comentarios inline publicados en el PR. Los hallazgos que superan
# este límite se incluyen igualmente en el resumen del review (body), priorizando
# siempre los de mayor severidad (🔴 > 🟡 > 🔵).
MAX_INLINE_COMMENTS = int(os.getenv("MAX_INLINE_COMMENTS", 15))

# --- Controles de costo (todos opcionales, desactivados por defecto) ---

# Si es true, el prompt le pide a Claude que SOLO reporte bugs graves (🔴):
# vulnerabilidades, crashes, lógica rota. Omite mejoras de estilo/performance/
# legibilidad, que suelen ser la mayoría de los comentarios en PRs grandes.
ONLY_CRITICAL_SEVERITY = os.getenv("ONLY_CRITICAL_SEVERITY", "false").lower() == "true"

# Si es true, un archivo solo pasa por análisis semántico (Claude) cuando el
# análisis estático (Ruff/ESLint) ya encontró algo en sus líneas nuevas. Los
# archivos "limpios" no cuestan tokens.
TWO_PASS_MODE = os.getenv("TWO_PASS_MODE", "false").lower() == "true"

# Si es true, solo se llama a Claude en archivos "riesgosos": cuyo nombre matchea
# RISKY_FILE_PATTERNS o cuyo patch supera RISKY_PATCH_SIZE líneas nuevas. El resto
# se queda solo con análisis estático.
RISKY_FILES_ONLY = os.getenv("RISKY_FILES_ONLY", "false").lower() == "true"
RISKY_FILE_PATTERNS = [
    p.strip().lower()
    for p in os.getenv(
        "RISKY_FILE_PATTERNS", "auth,payment,pago,db,database,secret,crypto,session,token"
    ).split(",")
    if p.strip()
]
RISKY_PATCH_SIZE = int(os.getenv("RISKY_PATCH_SIZE", 300))

# LLM Observatory — métricas de uso de Claude
OBSERVATORY_URL = os.getenv("OBSERVATORY_URL", "https://llm-web-production.up.railway.app")
OBSERVATORY_TOKEN = os.getenv("OBSERVATORY_TOKEN")  # obs_sk_...; si falta, no se envían métricas

# Contenido de la key (Railway/prod) o ruta al archivo (desarrollo local)
_key_content = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
_key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "private-key.pem")

def get_private_key() -> str:
    if _key_content:
        return _key_content.replace("\\n", "\n")
    with open(_key_path, "r") as f:
        return f.read()

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}
