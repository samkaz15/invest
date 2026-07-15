#!/bin/bash
# Daily backup (Constitution Art.8-3: data is the asset).
# Priority order: DB dump (events/evidences/decisions) + raw store.
# Schedule via cron/launchd; quarterly restore drill per docs/runbooks/.
set -euo pipefail

BACKUP_DIR="${BIOS_BACKUP_DIR:-$HOME/bios-backups}"
STAMP="$(date -u +%Y%m%d)"
PG_DUMP="${PG_DUMP:-/opt/homebrew/opt/postgresql@16/bin/pg_dump}"
DB_URL="${BIOS_DATABASE_URL:-postgresql://localhost/bios}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$BACKUP_DIR"
"$PG_DUMP" --format=custom --file="$BACKUP_DIR/bios-$STAMP.dump" "$DB_URL"
tar -czf "$BACKUP_DIR/raw-$STAMP.tar.gz" -C "$REPO_DIR" var/raw 2>/dev/null || true

# Retain 30 days locally; offsite sync is the owner's rclone/cloud step.
find "$BACKUP_DIR" -name "*.dump" -mtime +30 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
echo "backup complete: $BACKUP_DIR/bios-$STAMP.dump"
