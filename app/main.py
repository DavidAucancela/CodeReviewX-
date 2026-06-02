import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from app.webhook_handler import verify_signature, parse_pr_event
from app.pipeline import run_review_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Code Review Bot iniciado")
    yield
    logger.info("Code Review Bot detenido")


app = FastAPI(title="Code Review Bot", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


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

    # Corre el pipeline en background para no bloquear la respuesta al webhook
    asyncio.create_task(
        asyncio.to_thread(
            run_review_pipeline,
            repo=pr_data["repo_full_name"],
            pr_number=pr_data["pr_number"],
            installation_id=pr_data["installation_id"],
        )
    )

    return {"status": "processing", "pr": pr_data["pr_number"]}
