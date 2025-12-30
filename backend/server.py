import os
import asyncio
from contextlib import asynccontextmanager

import uvicorn
import redis.asyncio as redis
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware

# -------------------------------------------------------------------
# App-level utilities (replace with your own implementations)
# -------------------------------------------------------------------

from app.core.config import settings
from app.core.logging import get_logger
from app.core.background import start_background_tasks, stop_background_tasks
from app.core.models import init_models
from app.core.sessions import SessionManager

from app.api.routers import (
    chat_router,
    auth_router,
    prompt_router,
    knowledge_base_router,
)

# -------------------------------------------------------------------
# Globals
# -------------------------------------------------------------------

logger = get_logger("fastapi")
background_tasks: list[asyncio.Task] = []

IS_PROD = settings.env == "DEP"

# -------------------------------------------------------------------
# Lifespan (startup / shutdown)
# -------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Centralized startup / shutdown logic.
    Everything attached to app.state lives for the app lifetime.
    """
    logger.info("Starting application")

    # ---- Infrastructure clients ----
    app.state.redis = redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    app.state.session_manager = SessionManager(
        app.state.redis,
        session_ttl=3600,
    )

    # ---- DB / models ----
    await init_models(settings.db_engine)

    # ---- Background tasks ----
    background_tasks.extend(await start_background_tasks(app))
    logger.info("Background tasks started")

    # ---- Templates ----
    app.state.templates = Jinja2Templates(
        directory=settings.templates_path
    )

    yield

    # ---- Shutdown ----
    logger.info("Shutting down application")

    await stop_background_tasks(background_tasks)

    await app.state.redis.close()

    logger.info("Shutdown complete")

# -------------------------------------------------------------------
# App initialization
# -------------------------------------------------------------------

app = FastAPI(
    title="FastAPI Starter",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
    lifespan=lifespan,
)

# -------------------------------------------------------------------
# Exception handling
# -------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    """
    HTML for browsers, JSON for API clients.
    """
    if exc.status_code != status.HTTP_401_UNAUTHORIZED:
        return await http_exception_handler(request, exc)

    accepts_html = "text/html" in request.headers.get("accept", "").lower()
    templates = request.app.state.templates

    if accepts_html:
        return templates.TemplateResponse(
            "unauthorized.html",
            {
                "request": request,
                "reason": exc.detail,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# -------------------------------------------------------------------
# Middleware
# -------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Static files & templates
# -------------------------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory=settings.static_path),
    name="static",
)

# -------------------------------------------------------------------
# Routers
# -------------------------------------------------------------------

app.include_router(chat_router, prefix="/chat")
app.include_router(auth_router, prefix="/auth")
app.include_router(prompt_router, prefix="/prompts")
app.include_router(knowledge_base_router, prefix="/kb")

# -------------------------------------------------------------------
# Basic routes
# -------------------------------------------------------------------

@app.get("/")
async def root():
    return {"message": "Welcome to the FastAPI service"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(
        os.path.join(settings.static_path, "favicon.ico")
    )

# -------------------------------------------------------------------
# Local dev entrypoint
# -------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=not IS_PROD,
        reload_excludes=[
            "./bucket/*",
            "./bucket/prompts/*",
        ],
    )
