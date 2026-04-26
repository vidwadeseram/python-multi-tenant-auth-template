from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.middleware.tenant import tenant_context_middleware
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.utils.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(_: FastAPI):
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    yield


app = FastAPI(title="Python Multi-Tenant Auth Template", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
app.middleware("http")(tenant_context_middleware)
app.include_router(health_router)
app.include_router(auth_router)
