# P04 local production-readiness record — 16 September 2026

## Result and launch gate

The code-level privacy audit found four durable copies of submitted content beyond `checks.text_scrubbed`: quotes/details in `checks.verdict`, model-response cache files, unreviewed donations and bot thread state. The retention job now handles the first three plus feedback comments, and the bot masks and expires its own thread state. Compose starts the DB/cache retention job after the API becomes healthy. The API healthcheck now checks the JSON `ok` field, not just HTTP 200. Proxy trust now defaults to off.

**Public launch remains blocked.** This Windows machine has no `docker`, `podman` or `nerdctl` command, WSL reports that it is not installed, and there is no local PostgreSQL client. An actual Compose build, empty-Postgres migration, restart persistence, browser-to-API request, backup restore, and live log/proxy check have **not run**. There is no project `.env`; account credentials, bot token, domain and hosting are tracked separately, outside the repository. Passing SQLite tests does not establish those deployment facts.

| Check | Evidence on 16 September | Status |
|---|---|---|
| Compose build/config/start | Runtime commands absent; WSL not installed | Blocked: run on Docker-capable host |
| Migration on empty PostgreSQL | Alembic SQL covered by existing unit tests, no live database | Blocked |
| Restart persistence and web-to-API routing | Code/Compose path inspected, no running stack | Blocked |
| Retention | Representative SQLite tests for old/fresh verdicts, text, donations, comments and cache; bot-state test | Local code check only |
| Secrets, proxy, abuse | Placeholder HMAC secret rejected by `db.hashing`; Compose `TRUST_PROXY` now defaults to `0`; API limit and Turnstile paths inspected | Edge configuration and live abuse checks pending |
| Logs | API/bot/web application log call sites reviewed; no intentional submitted-text logging found; bot logs truncated HMAC references | Review real access/error logs and host retention before launch |

Local checks completed on this working tree: Ruff lint and format passed (`88` Python files formatted); offline pytest passed **1,370**, skipped **1**, expected failures **2** (21 network/LLM tests deselected); the affected API, bot, DB and repo test set passed. Web typecheck passed, all **9** web tests passed, the production build generated **135** static pages, and the sample smoke script passed **20** pages plus **4** invalid samples. The Next build still warns about a missing production `metadataBase`, already recorded in P01. Python YAML parsing found all five Compose services and the retention dependency, but it is not a substitute for `docker compose config`.

## Local validation on a Docker-capable machine

Use a **new, isolated Compose project name** and synthetic messages. The commands below assume PowerShell and default database names. Do not reuse a project that already has a `pgdata` volume for the empty-database check.

1. Create `.env` from `.env.example` outside version control. Set a long random `POSTGRES_PASSWORD` and `ACTOR_HASH_SECRET`; replace every `change_me` value. Fill `SAQBOL_SITE_URL` with the intended local/public origin. Supply provider keys and `TELEGRAM_BOT_TOKEN` only when testing those services. Keep `TRUST_PROXY=0` for the first local run. Confirm key **names**, not values, in the review record.
2. Run `docker compose -p saqbol-p04-20260916 config --quiet`, then `docker compose -p saqbol-p04-20260916 up -d --build db api web retention`. With a real bot token, start `bot` as well and verify long polling. Record image IDs and `docker compose -p saqbol-p04-20260916 ps` health states. A missing API health state blocks subsequent checks.
3. Confirm the migration with `docker compose -p saqbol-p04-20260916 exec api alembic current` and, in a DB shell, `psql -U saqbol -d saqbol -c '\dt'`. The revision must equal the repository head and `checks`, `feedback`, `dataset_candidates`, `rate_limits`, and `stats_daily` must exist. Capture sanitized output. Check `GET http://127.0.0.1:8000/healthz` and `GET http://127.0.0.1:3000/ru`.
4. Submit a distinctive **synthetic** message through the actual web form at `http://127.0.0.1:3000/ru`. Record its check ID, then query that ID in `checks` and confirm `surface='web'`. Confirm the web container has `SAQBOL_API_BASE=http://api:8000`; a rendered mock verdict is not routing evidence. Repeat after `docker compose -p saqbol-p04-20260916 restart api web` and verify the original row and daily limit remain. Then stop/start the isolated project **without `down -v`** and confirm the row remains.
5. In the isolated DB only, create an old synthetic check with a distinctive phrase in its text and evidence, a pending donated candidate linked to that check, an approved candidate, a feedback comment, and an aged cache cassette. Run `docker compose -p saqbol-p04-20260916 exec retention python -m saqbol.db.retention --dry-run`, then the real command. Check that old check text, verdict quotes/details, pending donation, comment and cassette disappear; summary metadata and approved donation remain. Repeat to confirm idempotence. Inspect `docker compose ... logs retention` for a successful first run and verify another run after a scheduled day. Test bot-state thread expiry with a real bot only if a token is available.
6. Inspect `docker compose ... logs api bot web retention` using only synthetic input. Search for the distinctive phrase, raw IP, Telegram ID, card digits, provider keys and request bodies. Check the reverse proxy/CDN and Docker host access/error log destinations and deletion interval too. Keep screenshots and captured log samples out of the repository.

## Proxy and abuse gate

`TRUST_PROXY=0` is the safe default: the API treats the socket peer as the actor, so web visitors may share a rate-limit bucket until the proxy is configured. Before setting `TRUST_PROXY=1`, make the public reverse proxy overwrite incoming `X-Forwarded-For` and `X-Real-IP` rather than append or pass them through, and prevent direct external access to ports 8000 and 5432. From two synthetic clients, verify separate daily buckets; send a forged forwarded header from one client and verify it does **not** create a third bucket. If that cannot be proven, leave public launch blocked. Confirm a real Turnstile key pair and its challenge path if the project requires browser abuse friction; a blank pair disables it. The API's daily limit remains the backstop.

## Operations: retention, backup, restore and rollback

- `retention` runs `python -m saqbol.db.retention` on startup and every 24 hours, with the API's database URL and shared `/app/.cache/llm` volume. Check its logs after every release and alert on a failed/restarting container. Its cutoff is `TEXT_RETENTION_DAYS` (default 30). It deletes stale pending/rejected **donated** candidates, clears old check text, redacts old verdict JSON, clears old feedback comments, and removes aged model-response files. Approved corpus rows remain. The bot independently masks its saved thread text, purges it on startup and hourly, and uses the configured 15-minute thread window by default.
- Keep encrypted Postgres backups off the app host, restrict access, and delete each backup within 30 days. Include `pgdata`, `botstate` and cache in the data inventory; do not copy the cache or bot state into long-lived diagnostics. Limit Docker/reverse-proxy logs to 30 days. PostgreSQL updates leave old tuple versions and WAL until vacuum/checkpoint and backup expiry; do not claim immediate physical erasure from a SQL `NULL` alone.
- For the **isolated synthetic** project, exercise a database backup and restore with the following PowerShell commands (adjust the DB user/name if `.env` differs):

  ```powershell
  $project = 'saqbol-p04-20260916'
  $dbContainer = docker compose -p $project ps -q db
  $backup = Join-Path $env:TEMP 'saqbol-p04-20260916.dump'
  docker compose -p $project exec -T db pg_dump -U saqbol -d saqbol -Fc -f /tmp/saqbol-p04.dump
  docker cp "${dbContainer}:/tmp/saqbol-p04.dump" $backup
  docker compose -p $project exec -T db createdb -U saqbol saqbol_restore_test
  docker compose -p $project exec -T db pg_restore -U saqbol -d saqbol_restore_test /tmp/saqbol-p04.dump
  docker compose -p $project exec -T db psql -U saqbol -d saqbol_restore_test -c 'SELECT count(*) FROM checks;'
  ```

  Confirm the restored synthetic check ID and Alembic revision. Remove the temporary local dump through the normal secure temporary-file cleanup after recording the result; do not put it in Git.
- Before changing schema or image versions, record immutable image IDs, the Alembic revision, configuration key names, and an encrypted `pg_dump -Fc` backup. Restore a copy into a **disposable** database with `pg_restore`, run `alembic current`, and run retention **before** accepting requests. Verify row counts and one synthetic check. A backup is not proven until this restore works.
- If a release fails, stop public routing and bot polling, restore the previous application images, and use the last compatible schema. If the migration is not backward-compatible, restore the tested DB backup into a fresh volume instead of downgrading blindly. Run retention on the restored copy, then repeat health, web-routing and persistence checks before reopening traffic. Never use `docker compose down -v` against a project containing user data.

## Remaining decisions

The owner must provide a Docker-capable validation host and deployment proxy configuration. An external provider, real bot token, domain/host and Turnstile keys are unverified in P02; no purchase, live deployment or message to others happened in P04. Review the bilingual privacy text before publication. Confirm backup, CDN and host log retention with the actual operator; the repository alone cannot enforce them.
