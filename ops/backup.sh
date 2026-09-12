#!/bin/bash
# Database backup (CONSTITUTION.md Art.8-3: data is the asset).
#
# ADR-010 puts the normalized truth in a managed PostgreSQL, outside git.
# data/raw/ and reports/ are committed, so git is their backup; the database
# is not, and losing it loses every past prediction vintage. That is the
# thing this script exists to prevent.
set -euo pipefail

BACKUP_DIR="${MIOS_BACKUP_DIR:-$HOME/mios-backups}"
STAMP="$(date -u +%Y%m%d)"
PG_DUMP="${PG_DUMP:-pg_dump}"
DB_URL="${MIOS_DATABASE_URL:?MIOS_DATABASE_URL must be set}"

mkdir -p "$BACKUP_DIR"
"$PG_DUMP" --format=custom --file="$BACKUP_DIR/mios-$STAMP.dump" "$DB_URL"

# Retain 30 days locally; offsite sync is the owner's step.
find "$BACKUP_DIR" -name "mios-*.dump" -mtime +30 -delete
echo "backup complete: $BACKUP_DIR/mios-$STAMP.dump"
