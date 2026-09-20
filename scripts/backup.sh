#!/bin/sh
set -eu

timestamp=$(date +%Y%m%d-%H%M%S)
backup_root=/backups
backup_dir="$backup_root/$timestamp"

mkdir -p "$backup_dir"
export PGPASSWORD="$POSTGRES_PASSWORD"

pg_dump \
  --host=db \
  --username="$POSTGRES_USER" \
  --format=custom \
  --file="$backup_dir/postgres.dump" \
  "$POSTGRES_DB"

tar -czf "$backup_dir/media.tar.gz" -C /source media
tar -czf "$backup_dir/private-invoices.tar.gz" -C /source private_invoices

pg_restore --list "$backup_dir/postgres.dump" >/dev/null
tar -tzf "$backup_dir/media.tar.gz" >/dev/null
tar -tzf "$backup_dir/private-invoices.tar.gz" >/dev/null
(
  cd "$backup_dir"
  sha256sum postgres.dump media.tar.gz private-invoices.tar.gz > SHA256SUMS
)

find "$backup_root" -mindepth 1 -maxdepth 1 -type d -mtime "+${BACKUP_RETENTION_DAYS:-30}" -exec rm -rf {} +
printf 'Sauvegarde créée : %s\n' "$backup_dir"