import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.cleanup import cleanup_loop
from app.config import settings
from app.rest_router import router as rest_router
from app.ws_router import router as ws_router

logger = logging.getLogger("chips")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.warning(
        "This app has no access control: anyone who can reach it can create a "
        "room, and anyone who knows or guesses a room code can take a seat."
    )
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(rest_router, prefix="/api")
app.include_router(ws_router)

if settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
