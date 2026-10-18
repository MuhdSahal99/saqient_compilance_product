# Deployment

Nothing in this repository provisions infrastructure, deploys automatically or
sends data to external services. The steps below are for a human operator.

## Local / single-host stack (Docker Compose)

```bash
cp .env.example .env            # optional; compose has development defaults
docker compose up -d --build    # db, redis, migrate (one-shot), api, worker, beat, web
docker compose exec api python -m app.seed --reset   # synthetic demo data, DEMO_MODE=true only
open http://localhost:8080
```

Services:

| Service | Image | Purpose |
|---|---|---|
| `db` | postgres:16-alpine | Database. Published on 127.0.0.1:`${DB_PORT:-5432}` for local tooling. |
| `redis` | redis:7-alpine | Celery broker and login rate limiting. No persistence. |
| `migrate` | backend image | Runs `alembic upgrade head` once, then exits. `api` and `worker` wait for it. |
| `api` | backend image | FastAPI on :8000 (internal only). Health: `/api/health`, readiness: `/api/health/ready` (checks DB and Redis). |
| `worker` | backend image | Celery worker: extraction, dataset imports, check runs, reminder emails. |
| `beat` | backend image | Celery beat: schedules the daily task due-date reminders (05:00 UTC). Run exactly one. |
| `web` | frontend image (nginx) | SPA plus `/api` reverse proxy on 127.0.0.1:`${WEB_PORT:-8080}`. Same origin, so the session cookie stays first-party. |

Volumes: `pgdata` (database) and `storage` (uploaded files, shared by `api` and
`worker`, mode 0600 per file).

Host ports can be changed with `DB_PORT`, `REDIS_PORT`, `WEB_PORT`.

Email: in development, invitations, password-reset links and reminders are
written as `.eml` files to `storage/mail/` in the `storage` volume (read them
with `docker compose exec api ls /data/storage/mail`). Nothing is sent.

## Production configuration

The API refuses to start with `APP_ENV=production` unless:

- `SECRET_KEY` is a random value of at least 32 characters (not the example value);
- `FIELD_ENCRYPTION_KEY` is 32 random bytes, base64-encoded (encrypts TRNs; losing it
  makes stored TRNs unreadable, so back it up with the database credentials);
- `DEMO_MODE=false` (demo users cannot sign in);
- `COOKIE_SECURE=true` (serve over HTTPS only);
- `CELERY_TASK_ALWAYS_EAGER=false`;
- the AI provider is not `mock`;
- `MAIL_BACKEND` is `smtp` (with `SMTP_HOST`) or `disabled`, and `APP_BASE_URL`
  is the https web URL used in email links.

Also set `CORS_ORIGINS` to the exact web origin, a strong `POSTGRES_PASSWORD`,
and keep `AI_ENABLED=false` unless docs/MODEL_INTEGRATION.md has been followed.

Secrets go in the host's secret store or an env file readable only by the
service account, never in the repository or image. Rotate `SECRET_KEY` by
deploying a new value; all sessions are then invalid.

## TLS

Terminate TLS in front of `web` (a managed load balancer, or Caddy/nginx with
certificates on the host). Forward `X-Forwarded-Proto`; the API sends HSTS in
production. Do not publish `db`, `redis` or `api` to the internet; in
production remove the `ports:` entries for `db` and `redis`.

## Migrations

`migrate` runs on every `docker compose up`. For a manual run:
`docker compose run --rm migrate`. Back up first. Migrations are forward-only
in normal operation; `alembic downgrade` exists for development.

## Backup and restore

Back up the database and the `storage` volume together, from the same point in time.

```bash
# Database (custom format)
docker compose exec -T db pg_dump -U saqient -d saqient -Fc > saqient-$(date +%F).dump
# Files
docker compose exec -T api tar -C /data -czf - storage > storage-$(date +%F).tgz

# Restore into an empty database
docker compose exec -T db psql -U saqient -d postgres -c "CREATE DATABASE saqient_restore"
docker compose exec -T db pg_restore -U saqient -d saqient_restore --no-owner < saqient-YYYY-MM-DD.dump
docker compose exec -T api tar -C /data -xzf - < storage-YYYY-MM-DD.tgz
```

Backups contain document text and personal data (names, emails). Encrypt them
and set a retention period; deleting a document in the app does not remove it
from existing backups (shown in the UI).

## Hosting options (GCP-first, not provisioned)

Two reasonable shapes. Choose with your security and data-residency
requirements; confirm the region is acceptable for the documents you will
store. No costs are quoted here: use the provider's pricing calculator with
your own sizing.

| | Single VM + Compose | Managed services |
|---|---|---|
| Components | One Compute Engine VM running this compose file; disk snapshots; TLS via a load balancer or Caddy | Cloud Run (api, web), a small Compute Engine VM for the Celery worker, Cloud SQL for PostgreSQL, Memorystore for Redis, Cloud Storage (`STORAGE_BACKEND=gcs`) |
| Operations | You patch the OS, Postgres and backups | Provider handles DB patching, backups, failover options |
| Fits | Pilots, small teams, demo environments | Multiple teams, higher availability needs |
| Main cost drivers | VM size, disk, snapshots, egress | Cloud SQL instance, Memorystore, always-on worker, egress |
| Changes needed | None | Configure GCS adapter credentials (workload identity), private networking between Cloud Run and Cloud SQL/Memorystore |

The S3 and GCS storage adapters exist but have not been tested against real
buckets in this repository (see docs/KNOWN_LIMITATIONS.md). GPUs are not
required: AI inference is disabled.
