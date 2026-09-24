# AG Solutions Tracking App

Internal order-tracking web application for **AG Solutions UAB**, a Lithuanian furniture brokerage. Gives a non-technical team real-time visibility into commercial orders — transport status, client deposits, factory deposits, and payment/production reminders — without asking staff to change how they already work in Google Sheets.

Fully deployed and running in production on a Raspberry Pi 4B at the office, reachable over a private Tailscale mesh network.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Data Flow](#data-flow)
- [Features](#features)
- [Project Structure](#project-structure)
- [Local Development](#local-development)
- [Environment Variables & Secrets](#environment-variables--secrets)
- [Google Sheets Integration](#google-sheets-integration)
- [Notifications](#notifications)
- [Internationalization](#internationalization)
- [Testing & CI](#testing--ci)
- [Deployment](#deployment)
- [Security](#security)
- [Backups](#backups)
- [Monitoring & Ops Scripts](#monitoring--ops-scripts)
- [Roadmap](#roadmap)
- [Known Gotchas / Operational Learnings](#known-gotchas--operational-learnings)
- [License](#license)

---

## Overview

Staff enter order data into a shared Google Sheet — no new tools for them to learn. A scheduled Celery Beat task pulls that sheet into PostgreSQL, and Django renders a dashboard showing, per order:

- Transport status (pending / confirmed / overdue)
- Client deposit status (deposit + final payment)
- Factory deposit status (deposit + final payment)
- Furniture and package-clarification reminders tied to production dates

When a reminder fires, staff get a push notification (via self-hosted ntfy) or an SMS fallback (via Seven.io), even with the browser closed.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Django (i18n, Celery, Celery Beat, django-celery-beat, django-celery-results) |
| Dependency management | `uv` (`pyproject.toml` + `uv.lock`) |
| App server | Gunicorn |
| Database | PostgreSQL |
| Task queue / scheduler | Celery + Celery Beat |
| Frontend | HTML, Tailwind CSS (CDN, no build step), vanilla JS |
| Reverse proxy / TLS | Nginx (HTTPS-only, port 80 → 443 redirect) |
| Push notifications | ntfy (self-hosted, Web Push / VAPID) |
| SMS fallback | Seven.io SMS API |
| Networking | Tailscale (private mesh, TLS termination for ntfy) |
| Secrets | Bitwarden Secrets Manager (`bws_init`, UUID-based) |
| Containerization | Docker / Docker Compose (3-file split: base, dev, prod) |
| Data source | Google Sheets (via `gspread` + Google Sheets API, service account auth) |
| CI | GitHub Actions, self-hosted Windows runner |
| Backups | rsync to a Synology DS218j NAS |
| Hardware | Raspberry Pi 4B (ARM64), booting from an external NVMe SSD (not SD card) |

## Architecture

```
Google Sheet ──(gspread, Celery Beat schedule)──> PostgreSQL ──> Django ──> Nginx (TLS) ──> Browser
                                                        │
                                                        └──> Celery worker ──> ntfy (Web Push) ──> Staff device
                                                                          └──> Seven.io SMS (fallback)

All traffic reaches the Pi over Tailscale (<URL>.ts.net).
Secrets fetched at container startup from Bitwarden Secrets Manager into a runtime-only volume.
```

Design decisions worth knowing:

- **Sheets is an input layer, not a live query source.** The app never hits the Sheets API on page load — `sync_sheet` runs on a Celery Beat schedule into Postgres, keeping page loads fast and avoiding Google API rate limits.
- **Deposit priority logic.** Each order can have a "Deposit" and a "Final Payment" row per side (client/factory). The dashboard surfaces whichever is still outstanding, in that priority order.
- **Reminder dates are computed, not hand-entered.** Transport, deposit, furniture, and package-clarification reminder dates are calculated on `save()` from their related due/production dates, so they can't drift out of sync with a manual edit.
- **Explicit hardcoded model fields over a generic rule engine.** New sheet columns are mapped deliberately rather than auto-styled by naming convention, trading some flexibility for clarity and fewer surprises.
- **3-file Compose split.** `docker-compose.yml` (base — shared `collectstatic` + gunicorn command, so dev and prod inherit it), `docker-compose.dev.yml` (bind mounts, `runserver` for live reload), `docker-compose.prod.yml` (bakes code via `COPY . .`, no bind mounts, Gunicorn).

## Data Flow

1. Non-technical staff update the shared Google Sheet (`Sheet1`).
2. A Celery Beat–scheduled task runs `python manage.py sync_sheet`, which reads the sheet via a service account, parses currency/date fields defensively, and upserts `Client`, `Order`, `ClientOrder`, `FactoryOrder`, `DepositClient`, `DepositFactory`, and `Transport` rows.
3. Orders no longer present in the sheet are removed from the database on the next sync.
4. The tracking page queries Postgres only, computing display status (paid / due / overdue, days remaining, reminder-sent state) per order at render time.
5. A separate scheduled task checks for due reminders and pushes notifications via ntfy, with Seven.io SMS as a fallback channel.

## Features

- 🔍 Live search by contract number / client name
- 🧮 Filter by payment status, transport status, or reminder type
- 🌗 Dark/light mode with persistence across pages
- 📊 Dynamic stat cards (no hardcoded numbers)
- 🔔 Explicit, unambiguous reminder badges (e.g. "Transport reminder sent" vs "Client reminder sent" vs "Factory reminder sent")
- 📲 Desktop/mobile push notifications (ntfy) with SMS fallback (Seven.io) for reminders
- 🌐 Full EN/LT interface translation, toggle-controlled via a `SiteSettings` singleton
- 🛡️ Graceful handling of malformed/empty sheet rows and duplicate contract numbers
- 📱 Mobile-responsive dashboard (accessed from phones on office Wi-Fi and over Tailscale)

## Project Structure

```
core/                   # Django project settings, URLs, WSGI/ASGI, Celery app config
main/                   # Primary app
├── management/
│   └── commands/
│       ├── sync_sheet.py     # Google Sheet -> Postgres sync
│       └── debug_sheet.py    # Prints raw sheet headers/rows for troubleshooting
├── migrations/
├── static/main/js/           # darkmode.js, filter.js, login.js
├── templates/main/           # login_page.html, main_offer_page.html
├── templatetags/
│   └── main_extras.py        # badge/status class filters
├── tests/                     # test_services, test_models, test_models_recovery,
│                               # test_views, test_tasks, test_sync_sheet
├── admin.py
├── models.py
├── urls.py
└── views.py
docker-compose.yml            # base — shared collectstatic + gunicorn command
docker-compose.dev.yml        # dev overrides — bind mounts, runserver
docker-compose.prod.yml       # prod overrides — baked code, Gunicorn
docker-compose.ci.yml         # CI overrides
pyproject.toml / uv.lock      # dependency management (uv)
manage.py
```

## Local Development

**Requirements:** Docker Desktop (or Docker Engine + Compose plugin)

```bash
git clone <repo-url>
cd <repo-folder>
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The app will be available at `http://localhost:8000/`.

On first run, apply migrations:

```bash
docker compose exec web python manage.py migrate
```

Create a superuser to access Django admin:

```bash
docker compose exec web python manage.py createsuperuser
```

Pull data from the configured Google Sheet:

```bash
docker compose exec web python manage.py sync_sheet
```

If no sync has run yet, the tracking page shows an empty state prompting a manual `sync_sheet` run.

> **Note:** the virtualenv lives at `/opt/venv`, outside `/app`, specifically so the dev bind mount doesn't shadow it.

## Environment Variables & Secrets

Secrets are managed centrally in **Bitwarden Secrets Manager**, referenced by UUID, and fetched at container startup by `bws_init` into a runtime-only volume (`/runtime-secrets`) — never baked into the image or committed to git.

| Category | Examples |
|---|---|
| Django | `SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` (must include the `.ts.net` Tailscale hostname) |
| Database | Postgres user/password/db (read from secret files, not plain env vars) |
| Google Sheets | `GOOGLE_SHEETS_CREDENTIALS_PATH`, `GOOGLE_SHEET_ID_PATH` |
| Notifications | `NTFY_USER`, `NTFY_PASSWORD`, `NTFY_TOPIC` (web/celery env only — never shared with the ntfy container's own env file), Seven.io API key |

What goes in Bitwarden vs. what's hardcoded: genuine secrets (passwords, API keys, `SECRET_KEY`) live in Bitwarden; public/non-sensitive values (base URLs, topic names, contact emails, resource IDs that don't grant access alone) are hardcoded.

`nginx.prod.conf` and `ntfy/server.yml` are environment-specific and gitignored; committed `.example` templates exist as reference.

## Google Sheets Integration

- Data lives in a single tab, `Sheet1`, with the header row at a fixed row number.
- Column headers are in Lithuanian; the exact header text is mapped in `SHEET_COLUMNS` inside `sync_sheet.py`. If your sheet's headers differ even slightly (typo, extra space, punctuation), update the mapping there — don't rename the sheet to match the code.
- Amount parsing treats `-`/`—` as zero, strips currency symbols and thousands separators.
- A deposit/final payment is considered **paid** if the total amount is `0`, or the amount paid equals the total. This is recalculated on every sync and should not be hand-edited afterward — the next sync will overwrite it.
- Run `python manage.py debug_sheet` to print the raw headers and first data row when diagnosing a mapping mismatch.

## Notifications

- **ntfy** is self-hosted and handles Web Push (VAPID) delivery to staff browsers — confirmed reliable for background/closed-browser delivery on Microsoft Edge for Windows (Chrome has unresolved delivery issues; Firefox is unreliable for closed-browser delivery on Windows, so both are skipped for staff rollout).
- **Seven.io SMS** serves as a fallback channel and for operational health alerts (e.g. heartbeat pings).
- ntfy terminates its own TLS on port 8443 via a Tailscale-issued certificate, separate from Nginx's TLS termination for Django.

## Internationalization

- Full EN/LT translation via Django's i18n framework.
- A custom `SiteLanguageMiddleware` overrides `LocaleMiddleware` so the in-app toggle is authoritative rather than browser `Accept-Language` headers.
- A `SiteSettings` singleton model stores the active language; background/notification code wraps output in `translation.override(SiteSettings.get_language())` so scheduled tasks respect the same setting as the UI.

## Testing & CI

- **204 Django tests** across `main/tests/`: `test_services.py`, `test_models.py`, `test_models_recovery.py`, `test_views.py`, `test_tasks.py`, `test_sync_sheet.py` — all passing. +80% test coverage through whole codebase.
- **CI** runs on a self-hosted GitHub Actions runner on the Windows dev machine (under Lottie's own Windows account, since `NETWORK SERVICE` has no Docker Desktop session). On every push it builds images, runs `manage.py check`, and runs `makemigrations --check --dry-run` against dummy secrets — this has caught multiple real missing-migration incidents.
- `docker-compose.dev.yml` and `docker-compose.ci.yml` are tracked in git; CI depends on them.
- The CI dummy-secrets step must be updated whenever a new required secret is added to `settings.py`.

## Deployment

Runs on a Raspberry Pi 4B (ARM64), booting from an external NVMe SSD, reachable via Tailscale (`<URL>.ts.net`).

Standard deploy from the Pi:

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

A dedicated `migrate` service applies migrations automatically as part of the compose stack. Containers run with `restart: unless-stopped` so they recover automatically after a power cut or reboot.

Because prod bakes code via `COPY . .` (no bind mounts), any file generated inside a running prod container (e.g. migrations created via `exec`) exists only in the ephemeral writable layer and is lost on rebuild — copy it out immediately with `docker compose cp`, or better, generate it in the dev environment where it persists via bind mount.

## Security

- Layered access: Nginx IP allowlist (office LAN / Tailscale) → Nginx HTTP Basic Auth → Django's own per-user login (`@login_required`).
- HTTPS-only Nginx, port 80 redirects to 443; `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` are both `False`. In production, they are `True`.
- Password hashing: Argon2 as the primary hasher, with PBKDF2/BCrypt/Scrypt retained as fallback verifiers so any pre-existing hashes upgrade transparently on next login.
- Rate limiting on the login endpoint to deter brute force.
- No public exposure — no port-forwarding; access is LAN/Tailscale-only by design.
- Secrets never touch the image or git history; fetched at runtime from Bitwarden Secrets Manager.

## Backups

- PostgreSQL dump and the ntfy `webpush.db` are backed up via `rsync` over SSH to a Synology DS218j NAS, using an atomic stage → validate → rename pattern.
- Code, configuration, and secrets are intentionally excluded from NAS backups — they live in Git and Bitwarden respectively.

## Monitoring & Ops Scripts

Operational scripts live in `~/scripts/` on the Pi, with logs in `~/logs/` and rotation configured via `/etc/logrotate.d/ag-solutions-scripts`. Current scripts:

- `disk-alert` — disk usage threshold alerting
- `vacuum-weekly` — scheduled Postgres vacuum
- `pg-connections-alert` — Postgres connection count alerting
- `ntfy_health_ping` — heartbeat check with SMS fallback if ntfy is unreachable
- `docker-image-prune` — periodic cleanup of unused images
- `temp-alert` — Pi temperature monitoring
- `smart-check` — SSD SMART health check
- `restart-loop-check` — detects containers stuck in a restart loop

## Roadmap

The primary remaining milestone is a **CD pipeline with an integrated OWASP ZAP security audit**, being built as part of ongoing thesis (BD) work:

- [ ] Staging environment (planned to run ephemerally on the Windows CI runner, not the Pi, to avoid resource contention with production)
- [ ] Unit tests → integration tests → UX/e2e tests → OWASP ZAP, run in that order, with ZAP gated behind all functional tests passing
- [ ] Decide: unit/integration tests against the staging stack or a separate throwaway DB
- [ ] Decide: adopt Playwright for e2e tests
- [ ] Decide: whether ZAP failures block deployment or only produce report artifacts

> This section will be updated with the finished CD pipeline once the thesis defence is complete.

*Note: Dependabot is intentionally not used — package versions are pinned deliberately, and an unreviewed automated dependency bump could break production.*

## Known Gotchas / Operational Learnings

**Secrets & startup**
- `bws_init`'s entrypoint does not propagate CLI failures by default — it can report success while every secret fetch silently failed (wrong architecture binary, bad/expired token), writing empty files. Symptom: a confusing Postgres crash loop ("superuser password is not specified"). Harden with `set -euo pipefail` and explicit exit-code checks.
- Bitwarden references secrets by UUID, not name — check the UUID reference in `bws_init` before deleting any Bitwarden entry.
- ntfy's `server.yml` does not dereference file paths — it treats a path string as a literal value. Workaround: `sed` placeholder substitution at container startup.

**Cross-architecture Docker builds**
- Hardcoded `curl`/`wget` URLs to architecture-specific release assets build successfully on both x86_64 and ARM64 but fail at runtime on the Pi with "Exec format error" — silently swallowed without `set -e`. Fix: detect `uname -m` at build time and select the correct asset.
- `COPY --from=` multi-stage steps auto-resolve per architecture; hardcoded download URLs do not.

**Prod containers**
- Prod bakes code via `COPY . .`; anything generated inside a running prod container via `exec` is lost on rebuild. Copy it out immediately, or generate it in dev instead.
- Always rebuild (`--build`), not just restart, after host-side source edits.

**Nginx**
- Bare `proxy_pass http://web:8000;` resolves the upstream IP once at config-load time; when Compose recreates `web` with a new IP, Nginx keeps hitting the stale one and returns 502. Fix: `resolver 127.0.0.11 valid=10s;` plus a variable (`set $upstream_web http://web:8000; proxy_pass $upstream_web;`) in every location block.
- Bind-mounted config edits do not trigger a reload — run `docker compose exec nginx nginx -s reload` (or `--force-recreate nginx`) after any config change.

**Django i18n**
- `compilemessages` compares timestamps inside the running container, not the host's edited `.po` file — always rebuild the image → run `compilemessages` in a fresh container → `docker compose cp` the `.mo` back out → rebuild again.
- The `#, fuzzy` flag silently excludes entries from compilation with no warning — `grep -n "fuzzy" django.po` after every `makemessages` run; strip with `sed -i '/^#, fuzzy/d; /^#|/d'`.
- `%(days)s` vs `%(day)s` typos in format strings cause `compilemessages` to silently fail.

**Celery Beat**
- A periodic task scheduled both in `celery.py`'s `beat_schedule` and via a Django admin `PeriodicTask` row will fire from both independently — editing the interval in admin appears to do nothing because the hardcoded schedule keeps firing. Check for duplicate enabled `PeriodicTask` rows.

**Environment files**
- Never let a server process and its authenticating client share an `env_file` — same-named variables silently collide. (`NTFY_PASSWORD` from the Django/Celery env hijacked `ntfy user change-pass` CLI calls until split into a dedicated `.env.ntfy`.)

**Git**
- `git filter-repo` must run from a fresh clone, needs a `--force --all` push afterward, and every other checkout (including the Pi) needs a fresh re-clone since commit hashes change.

**PowerShell**
- `echo >` defaults to UTF-16 and corrupts files read via `cat` in shell scripts — use `Set-Content -Encoding ascii -NoNewline` for CI-generated secret/env files.

**General**
- Django template links must use named URL patterns (`/main_offer_page/`), never raw file paths.
- `INSTALLED_APPS` entries and each app's `apps.py` `name` must exactly match the app's folder name, or you'll hit `ImproperlyConfigured`.
- Writing tests for "already manually verified" code can catch real bugs — e.g. `logout_view` never called Django's `logout()`, so sessions were never actually terminated.

## License

Internal tool — all rights reserved, AG Solutions UAB.
