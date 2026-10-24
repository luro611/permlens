#!/bin/sh
# Feste Versionen mit Prüfsummen neu erzeugen (requirements.in → requirements.txt).
# Läuft in einem Python-3.12-Container unter Linux, also genau wie das Image von PermLens.
# Danach: Unterschiede ansehen (git diff requirements.txt), Tests laufen lassen, committen.
set -e
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c '
  pip install -q pip-tools &&
  pip-compile -q --generate-hashes --strip-extras --allow-unsafe --no-header -o /tmp/req.txt requirements.in &&
  { echo "# Fest angegebene Versionen mit Prüfsummen (erzeugt mit pip-compile unter Python 3.12/Linux)."
    echo "# Nicht von Hand ändern, sondern: sh tools/lock.sh  (liest requirements.in)"
    cat /tmp/req.txt; } > requirements.txt'
echo "requirements.txt erneuert. Jetzt: git diff requirements.txt und Tests."
