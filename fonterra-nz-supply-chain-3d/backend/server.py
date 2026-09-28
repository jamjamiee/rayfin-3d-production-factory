"""Local-only KQL adapter. Do not expose Azure CLI credentials through a public deployment."""

import argparse
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .kql import FeedError, KqlFeed, Settings


def create_app(feed=None):
    @asynccontextmanager
    async def lifespan(app):
        if feed is None:
            app.state.feed = KqlFeed(Settings.from_environment())
        else:
            app.state.feed = feed
        yield
        if feed is None:
            app.state.feed.close()

    app = FastAPI(title="Fonterra NZ Supply Chain - local data adapter", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.exception_handler(FeedError)
    async def feed_error(_request, error: FeedError):
        return JSONResponse(status_code=error.status,
                            content={"error": {"code": error.code, "message": error.message}},
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/factory/snapshot")
    def snapshot():
        return JSONResponse(content=app.state.feed.snapshot().model_dump(mode="json"),
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/health")
    def health():
        return {"status": "ready", "mode": "local-read-only", "source": "FonterraSales"}

    @app.get("/api/{path:path}")
    def unknown_api(path: str):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Unknown API route."}})

    dist = Path(__file__).resolve().parents[1] / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unprivileged port from 1024 to 65535.")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
