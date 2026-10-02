# Pi host cron jobs (external to the Django stack)

Scope: jobs in the **Raspberry Pi's own crontab** (user `admin_banana_pie`), plus the OS's default schedulers.
Jobs scheduled inside the stack (Celery Beat: `sync_sheet_task`, reminder checks, etc.) are **not** listed here.

Verified against `crontab -l` on **2026-10-02**. Root has no crontab.
Purposes are inferred from the script names, so correct them if a script does something different.

All scripts live in `/home/admin_banana_pie/scripts/`. Logs go to `/home/admin_banana_pie/logs/` (stdout and stderr appended).

## User crontab (`crontab -l`)

| Schedule | Meaning | Script | Log | Purpose |
|----------|---------|--------|-----|---------|
| `* * * * *` | every minute | inline `docker compose ps ... \| grep -qx web && curl <HC_PING_URL>` | none (healthchecks.io dashboard) | Dead-man's switch: pings only if the `web` container is running |
| `*/10 * * * *` | every 10 min | `restart-loop-check.sh` | `restart-loop-check.log` | Detects containers stuck restarting |
| `*/15 * * * *` | every 15 min | `temp-alert.sh` | `temp-alert.log` | Alerts on high CPU temperature |
| `0 3 * * *` | daily 03:00 | `vacuum-kombu.sh` | `vacuum-kombu.log` | Cleans up the Celery/kombu message tables |
| `0 6 * * *` | daily 06:00 | `smart-check.sh` | `smart-check.log` | SSD SMART health check |
| `0 7 * * *` | daily 07:00 | `ntfy_health_ping.sh` | `ntfy_heartbeat.log` | Daily heartbeat (ntfy, SMS fallback) |
| `0 8 * * *` | daily 08:00 | `disk-alert.sh` | `disk-alert.log` | Alerts on low disk space |
| `0 3 * * 1` | Mondays 03:00 | `renew-certs.sh` | `cert-renew.log` | Renews the HTTPS certificate |
| `0 4 * * 0` | Sundays 04:00 | `nas-backup.sh` | `nas-backup.log` | Weekly backup to the DS218j NAS |
| `0 5 * * 0` | Sundays 05:00 | `docker-image-prune.sh` | `docker-prune.log` | Removes unused Docker images |

`<HC_PING_URL>` is the full hc-ping.com URL. It is a secret: keep it in Bitwarden, not in git or this file.
The healthchecks.io check's **Period** must be set to **1 minute** (with a few minutes of grace) to match the every-minute schedule.

## OS-provided schedulers

- `/etc/cron.d/`: `e2scrub_all`
- `/etc/cron.daily/`: `apt-compat`, `dpkg`, `logrotate`, `man-db`
- `/etc/cron.hourly/`: empty
- systemd timers: `apt-daily`, `apt-daily-upgrade`, `dpkg-db-backup`, `logrotate`, `man-db`, `systemd-tmpfiles-clean`, `rpi-zram-writeback`, `e2scrub_all`, `fstrim`

## Notes

- Cron runs with a minimal environment: use absolute paths, add `cd` where a command depends on the working directory, and redirect output to a log (`>> ~/logs/<name>.log 2>&1`) so failures can be debugged.
- Monday 03:00 has two jobs at the same time (`renew-certs.sh` and `vacuum-kombu.sh`). This is harmless unless one of them restarts a container the other needs.
- The Google Sheet sync is **not** a host cron. It runs as a Celery task, so code changes take effect only after a stack rebuild.
- To re-verify this list: `crontab -l`, `sudo crontab -l`, `ls /etc/cron.d /etc/cron.daily /etc/cron.hourly`, `systemctl list-timers --all`.

## Testing a job over SSH

- Run the command by hand and check that `echo $?` prints `0`.
- Temporarily set the schedule to `* * * * *`, wait two minutes, then check `grep CRON /var/log/syslog | tail` (or `journalctl -u cron --since "5 min ago" --no-pager`). Restore the real schedule afterwards.
- healthchecks.io alert test: `curl -fsS -m 10 -o /dev/null <HC_PING_URL>/fail`, then send a normal ping to recover.
- Don't test by cutting the network, because it locks you out of the Pi.
