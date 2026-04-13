import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.config import settings
from src.errors import OAuthError
from src.keys import load_keys
from src.routes import admin, authorize, health, openshift_callback, token, well_known

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("memoryhub-auth")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_keys()
    log.info("MemoryHub Auth started — issuer=%s", settings.issuer)
    yield


app = FastAPI(
    title="MemoryHub Auth",
    description="OAuth 2.1 Authorization Server for MemoryHub",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(OAuthError)
async def oauth_error_handler(request, exc: OAuthError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.error_description},
    )


app.include_router(token.router)
app.include_router(authorize.router)
app.include_router(openshift_callback.router)
app.include_router(well_known.router)
app.include_router(health.router)
app.include_router(admin.router)


def main():
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
