"""The HTTP surface: docs/02_DATA_CONTRACTS.md section 5.

    uvicorn saqbol.api.main:app

Runs with nothing configured: no `DATABASE_URL` means an in-memory store, no
provider key means the rules-only pipeline. Every handler is async and every
database call goes through a worker thread, so one slow query cannot stall
the event loop for everyone else.

Two rules hold throughout this module. Request text and client addresses never
reach a log line; a log line carries a check id, a band and a latency, nothing
else. And the only identifier that reaches the database is the HMAC of the
client address, produced by `saqbol.db.hashing`.

Error bodies are `{"error": <code>, ...}` for every status, including the
ones FastAPI would otherwise answer with `{"detail": ...}`, so a client can
switch on one key.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text
from starlette.exceptions import HTTPException as StarletteHTTPException

from saqbol.api.deps import Deps, DepsDep, llm_configured
from saqbol.api.schemas import AnalyzeOut, FeedbackIn, HealthOut, PlaybookPublic
from saqbol.core.normalize import normalize
from saqbol.core.types import AnalysisInput
from saqbol.db.hashing import hash_actor
from saqbol.db.repo import Store, UnknownCheck

log = logging.getLogger("saqbol.api")

#: A request carrying this header with the value "web" is recorded as coming
#: from the web form; everything else is "api". The body's own `surface`
#: field is client-controlled and is not trusted for this.
SURFACE_HEADER = "X-Saqbol-Surface"

#: Where the socket peer is unknown every such request shares one bucket,
#: which errs on the side of limiting rather than of letting everything through.
UNKNOWN_PEER = "unknown"


class ApiError(Exception):
    """A status the contract spells out, with its `{"error": ...}` body."""

    def __init__(self, status: int, error: str, **extra: Any) -> None:
        super().__init__(error)
        self.status = status
        self.error = error
        self.extra = extra


# ----------------------------------------------------------------- helpers


def seconds_until_utc_midnight(now: datetime | None = None) -> int:
    """How long a rate-limited actor waits: the daily counter resets at 00:00 UTC."""
    current = now or datetime.now(UTC)
    midnight = datetime.combine(current.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return max(1, math.ceil((midnight - current).total_seconds()))


def decoded_image_size(image_b64: str) -> int:
    """Byte length the base64 payload decodes to, computed without decoding it.

    Accepts a data URL prefix and wrapped lines. The figure is exact for valid
    base64, and an upper bound for anything else, which is all a size limit needs.
    """
    payload = image_b64
    if payload.startswith("data:"):
        payload = payload.partition(",")[2]
    payload = "".join(payload.split())
    padding = len(payload) - len(payload.rstrip("="))
    return max(0, len(payload) * 3 // 4 - padding)


def client_address(request: Request, *, trust_proxy: bool) -> str:
    """The address the rate limit is keyed on. Hashed before it goes anywhere."""
    if trust_proxy:
        first = request.headers.get("x-forwarded-for", "").partition(",")[0].strip()
        if first:
            return first
    if request.client is not None and request.client.host:
        return request.client.host
    return UNKNOWN_PEER


def request_surface(request: Request) -> str:
    return "web" if request.headers.get(SURFACE_HEADER, "").strip().lower() == "web" else "api"


def _db_reachable(store: Store) -> bool:
    try:
        with store.engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    except Exception:
        return False
    return True


def _live_stats(store: Store) -> dict:
    # Cheap at this scale, and it means the public number is never a day stale.
    store.materialize_day(datetime.now(UTC).date())
    return store.stats_summary().as_dict()


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.post(
    "/api/v1/analyze",
    response_model=AnalyzeOut,
    responses={
        413: {"description": "text over MAX_TEXT_CHARS or image over MAX_IMAGE_BYTES"},
        422: {"description": "invalid body, empty input, or an image without text"},
        429: {"description": "daily limit reached; retry_after is seconds until UTC midnight"},
    },
)
async def analyze(body: AnalysisInput, request: Request, deps: DepsDep) -> AnalyzeOut:
    settings = deps.settings
    text = body.text or ""

    if len(text) > settings.max_text_chars:
        raise ApiError(413, "too_large")
    if body.image_b64 and decoded_image_size(body.image_b64) > settings.max_image_bytes:
        raise ApiError(413, "too_large")
    if not text.strip():
        # There is no OCR yet. Saying so beats returning a verdict on nothing.
        raise ApiError(422, "image_not_supported" if body.image_b64 else "empty_input")

    surface = request_surface(request)
    address = client_address(request, trust_proxy=settings.trust_proxy)
    actor = hash_actor(address, secret=deps.actor_secret)
    store = deps.store

    allowed = await asyncio.to_thread(store.spend_check, actor, limit=settings.daily_check_limit)
    if not allowed:
        raise ApiError(429, "rate_limited", retry_after=seconds_until_utc_midnight())

    started = time.perf_counter()
    verdict = await deps.analyzer(
        text, locale=body.lang_hint, surface=surface, thread=list(body.thread)
    )
    # The same call the pipeline makes, so the offsets in the verdict index this string.
    normalized = normalize(text, lang_hint=body.lang_hint).text
    if any(normalized[span.start : span.end] != span.text for span in verdict.evidence):
        log.warning("check %s: evidence offsets do not match the normalized text", verdict.check_id)

    await asyncio.to_thread(
        store.record_check,
        verdict,
        actor_hash=actor,
        text=normalized,
        surface=surface,
        input_type="text",
        consent_dataset=body.consent_dataset,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        "check %s band=%s latency_ms=%d model_ms=%d",
        verdict.check_id,
        verdict.band,
        elapsed_ms,
        verdict.latency_ms,
    )
    return AnalyzeOut.from_verdict(verdict, normalized)


@router.post(
    "/api/v1/feedback",
    status_code=204,
    response_class=Response,
    responses={404: {"description": "no check with that id"}},
)
async def feedback(body: FeedbackIn, deps: DepsDep) -> Response:
    try:
        await asyncio.to_thread(
            deps.store.record_feedback,
            body.check_id,
            was_correct=body.was_correct,
            comment=body.comment,
        )
    except UnknownCheck:
        raise ApiError(404, "unknown_check") from None
    return Response(status_code=204)


@router.get("/api/v1/stats")
async def stats(deps: DepsDep) -> dict:
    return await asyncio.to_thread(_live_stats, deps.store)


@router.get("/api/v1/playbooks", response_model=list[PlaybookPublic])
async def list_playbooks(deps: DepsDep) -> list[PlaybookPublic]:
    return [PlaybookPublic.from_playbook(pb) for _id, pb in sorted(deps.playbooks.items())]


@router.get(
    "/api/v1/playbooks/{playbook_id}",
    response_model=PlaybookPublic,
    responses={404: {"description": "no playbook with that id"}},
)
async def get_playbook(playbook_id: str, deps: DepsDep) -> PlaybookPublic:
    playbook = deps.playbooks.get(playbook_id)
    if playbook is None:
        raise ApiError(404, "unknown_playbook")
    return PlaybookPublic.from_playbook(playbook)


@router.get("/healthz", response_model=HealthOut)
async def healthz(deps: DepsDep) -> HealthOut:
    """Always 200; the booleans carry the detail. `ok` means checks can be served."""
    try:
        db = await asyncio.to_thread(_db_reachable, deps.store)
    except Exception:
        db = False
    return HealthOut(ok=db, db=db, llm=llm_configured())


# ------------------------------------------------------------ error bodies


async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
    headers = {}
    if "retry_after" in exc.extra:
        headers["Retry-After"] = str(exc.extra["retry_after"])
    return JSONResponse({"error": exc.error, **exc.extra}, status_code=exc.status, headers=headers)


async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"error": "invalid_input", "detail": jsonable_encoder(exc.errors())}, status_code=422
    )


async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    return JSONResponse(
        {"error": code, "detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


async def _unhandled(_request: Request, _exc: Exception) -> JSONResponse:
    # The traceback is logged by the server middleware; nothing about the request is.
    return JSONResponse({"error": "internal"}, status_code=500)


# --------------------------------------------------------------------- app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(app.state.deps.warm)
    yield


def create_app(deps: Deps | None = None) -> FastAPI:
    """Build the app. Pass a `Deps` to run it against your own store or limits."""
    app = FastAPI(title="SaqBol API", lifespan=lifespan)
    app.state.deps = deps or Deps()

    origins = app.state.deps.settings.cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", SURFACE_HEADER],
        )

    app.include_router(router)
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
    return app


app = create_app()

__all__ = ["ApiError", "app", "create_app", "router"]
