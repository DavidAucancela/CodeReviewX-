import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PORT = int(os.getenv("PORT", 8000))

# Contenido de la key (Railway/prod) o ruta al archivo (desarrollo local)
_key_content = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
_key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "private-key.pem")

def get_private_key() -> str:
    if _key_content:
        return _key_content.replace("\\n", "\n")
    with open(_key_path, "r") as f:
        return f.read()

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}
