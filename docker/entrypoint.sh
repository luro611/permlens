#!/bin/sh
# Startet PermLens als Benutzer permlens (10001), nicht als root.
# Startet der Container als root (Standard), wird nur der Daten-Ordner einmal an permlens übergeben
# (Daten aus Versionen bis 0.2.0 gehören noch root) und dann werden alle Rechte abgegeben.
set -e
DATA="${DATA_DIR:-/app/data}"
if [ "$(id -u)" = 0 ]; then
  mkdir -p "$DATA"
  if [ -n "$(find "$DATA" ! -user 10001 -print -quit)" ]; then
    chown -R 10001:10001 "$DATA"
  fi
  exec setpriv --reuid=10001 --regid=10001 --init-groups --inh-caps=-all --bounding-set=-all --no-new-privs \
    python -m app.serve
fi
exec python -m app.serve
