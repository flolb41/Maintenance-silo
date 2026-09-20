#!/bin/sh
set -eu

backup_root=/backups
backup_name=${1:-$(ls -1 "$backup_root" | sort | tail -n 1)}
backup_dir="$backup_root/$backup_name"

if [ -z "$backup_name" ] || [ ! -d "$backup_dir" ]; then
  echo "Sauvegarde introuvable : $backup_name" >&2
  exit 1
fi

cd "$backup_dir"
sha256sum -c SHA256SUMS
pg_restore --list postgres.dump >/dev/null
tar -tzf media.tar.gz >/dev/null
tar -tzf private-invoices.tar.gz >/dev/null
printf 'Sauvegarde vérifiée : %s\n' "$backup_name"