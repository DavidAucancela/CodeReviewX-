import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# Configura logging ANTES de importar los módulos de la app: semantic_analyzer
# loguea el proveedor al importarse, y sin esto el root logger está en WARNING
# y ese INFO se pierde (por eso "Proveedor de análisis semántico" nunca salía).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

from app.webhook_handler import verify_signature, parse_pr_event  # noqa: E402
from app.pipeline import run_review_pipeline  # noqa: E402
from app.semantic_analyzer import MODEL  # noqa: E402
from app import patterns_store  # noqa: E402
from config.settings import LLM_PROVIDER, PATTERNS_ADMIN_TOKEN, SELF_REPO  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        f"Code Review Bot iniciado — proveedor={LLM_PROVIDER} modelo={MODEL}"
    )
    yield
    logger.info("Code Review Bot detenido")


app = FastAPI(title="Code Review Bot", lifespan=lifespan)


@app.get("/health")
def health():
    # Expone el proveedor/modelo activo para poder verificar la configuración
    # sin abrir un PR de prueba. No incluye ninguna credencial.
    return {"status": "ok", "provider": LLM_PROVIDER, "model": MODEL}


_STATIC_DIR = Path(__file__).parent / "static"


def _check_admin_token(x_admin_token: str | None) -> None:
    if not PATTERNS_ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="PATTERNS_ADMIN_TOKEN no configurado")
    if x_admin_token != PATTERNS_ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")


class NewPattern(BaseModel):
    text: str
    source: str = ""


@app.get("/patterns", response_class=HTMLResponse)
def patterns_page():
    return FileResponse(_STATIC_DIR / "patterns.html")


@app.get("/patterns/api")
def patterns_list():
    try:
        history = patterns_store.fetch_history()
    except Exception as e:
        # El historial es un extra informativo — si GitHub falla (rate limit,
        # credenciales locales incompletas), la lista de patrones igual debe
        # cargar.
        logger.warning(f"No se pudo traer el historial de patrones: {e}")
        history = []

    return {
        "repo": SELF_REPO,
        "provider": LLM_PROVIDER,
        "model": MODEL,
        "patterns": patterns_store.load_local(),
        "history": history,
    }


@app.post("/patterns/api")
def patterns_add(body: NewPattern, x_admin_token: str = Header(None)):
    _check_admin_token(x_admin_token)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="El patrón no puede estar vacío")
    return patterns_store.add_pattern(body.text.strip(), body.source.strip())


@app.delete("/patterns/api/{pattern_id}")
def patterns_remove(pattern_id: str, x_admin_token: str = Header(None)):
    _check_admin_token(x_admin_token)
    if not patterns_store.remove_pattern(pattern_id):
        raise HTTPException(status_code=404, detail="Patrón no encontrado")
    return {"removed": pattern_id}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None),
):
    payload_bytes = await request.body()

    if not verify_signature(payload_bytes, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Firma inválida")

    if x_github_event != "pull_request":
        return {"ignored": True, "event": x_github_event}

    payload = await request.json()
    pr_data = parse_pr_event(payload)

    if not pr_data:
        return {"ignored": True, "reason": "acción no relevante"}

    logger.info(f"PR recibido: {pr_data['repo_full_name']}#{pr_data['pr_number']} ({pr_data['action']})")

    # Corre el pipeline en un hilo dedicado no-daemon, no en el event loop:
    #  - una tarea de asyncio.create_task sin referencia guardada puede ser
    #    recolectada por el GC a mitad de camino, y el loop la cancela en el
    #    shutdown → el review desaparecía sin postear nada.
    #  - un hilo no-daemon corre independiente del loop y mantiene vivo el
    #    proceso hasta terminar, así ni un apagado ordenado corta el review.
    threading.Thread(
        target=run_review_pipeline,
        kwargs={
            "repo": pr_data["repo_full_name"],
            "pr_number": pr_data["pr_number"],
            "installation_id": pr_data["installation_id"],
            "head_sha": pr_data["head_sha"],
        },
        name=f"review-{pr_data['repo_full_name']}#{pr_data['pr_number']}",
        daemon=False,
    ).start()

    return {"status": "processing", "pr": pr_data["pr_number"]}
