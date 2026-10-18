# One image for the two Python services. docker-compose.yml picks the command:
#   api: alembic upgrade head, then uvicorn on :8000
#   bot: python -m saqbol.bot.main (long polling, no public port)
#
# The `llm` extra is left out on purpose: the model client is plain urllib,
# and sentence-transformers would add several gigabytes of torch for the
# dense-retrieval ablation, which the leaderboard runs on a laptop, not here.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 1000 saqbol
WORKDIR /app

# Dependency layer first, so a code change does not reinstall the world.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[api,bot]"

# Migrations and the packaged data (playbooks, i18n, lexicons) ship with the wheel;
# alembic needs its own directory at runtime.
COPY alembic.ini ./
COPY alembic ./alembic

# The model response cache lives here when a volume is mounted at /app/.cache.
RUN mkdir -p /app/.cache /app/state && chown -R saqbol:saqbol /app
USER saqbol

EXPOSE 8000

# Default is the API; the bot service overrides this in compose.
CMD ["uvicorn", "saqbol.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
