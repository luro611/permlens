#!/bin/sh
# Öffentlichen Stand erzeugen (Weg A, Entscheidung Lutz 2026-10-22): Entwickelt wird im privaten Repository
# luro611/permlens-dev mit allem (Planung, Testumgebung, CLAUDE.md). Das öffentliche luro611/permlens bekommt
# je Release einen Commit „PermLens <Version>“ mit dem Stand ohne die Pfade aus tools/nicht-oeffentlich.txt.
#
#     sh tools/export-oeffentlich.sh            Stand von HEAD exportieren, prüfen, committen und pushen
#     sh tools/export-oeffentlich.sh --probe    nur exportieren und prüfen, nichts committen (zeigt den Ordner)
#
# Der öffentliche Klon liegt neben dem Projektordner in ../permlens-oeffentlich (änderbar mit PUBLIC_DIR).
# Normalerweise ruft tools/publish.sh dieses Skript auf.
set -e
cd "$(dirname "$0")/.."
PUBLIC_REPO=${PUBLIC_REPO:-luro611/permlens}
DIR=${PUBLIC_DIR:-../permlens-oeffentlich}
V=$(cat VERSION)
MODE=${1:-}

# Nie ins eigene Repository exportieren (vor dem Umbenennen ist origin noch luro611/permlens).
# Die Probe prüft nur den committeten Stand (HEAD) und darf deshalb auch vorher und mit offenen Änderungen laufen.
if [ "$MODE" != "--probe" ]; then
  case "$(git remote get-url origin)" in
    *"/$PUBLIC_REPO.git"|*"/$PUBLIC_REPO"|*":$PUBLIC_REPO.git")
      echo "Abbruch: origin ist $PUBLIC_REPO selbst. Erst das private Repository in permlens-dev umbenennen und"
      echo "  git remote set-url origin https://github.com/luro611/permlens-dev.git"
      exit 1;;
  esac
  if [ -n "$(git status --porcelain)" ]; then
    echo "Abbruch: Es gibt noch nicht committete Änderungen (git status)."; exit 1
  fi
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git archive HEAD | tar -x -C "$TMP"
grep -v -E '^[[:space:]]*(#|$)' tools/nicht-oeffentlich.txt | while IFS= read -r p; do rm -rf "${TMP:?}/$p"; done

# Prüfen: nichts aus der Liste darf übrig sein, keine Schlüssel, keine Angaben aus dem Heimnetz
grep -v -E '^[[:space:]]*(#|$)' tools/nicht-oeffentlich.txt | while IFS= read -r p; do
  if [ -e "$TMP/$p" ]; then echo "Abbruch: $p ist noch im öffentlichen Stand."; exit 1; fi
done
PAT=$(mktemp)
grep -v -E '^[[:space:]]*(#|$)' tools/nicht-oeffentlich-muster.txt > "$PAT"
HITS=$(mktemp)
grep -r -n -i -I -E -f "$PAT" "$TMP" > "$HITS" || true
rm -f "$PAT"
if [ -s "$HITS" ]; then
  sed "s|^$TMP/||" "$HITS"; rm -f "$HITS"
  echo "Abbruch: Die Zeilen oben gehören nicht in den öffentlichen Stand."; exit 1
fi
rm -f "$HITS"
echo "Geprüft: $(find "$TMP" -type f | wc -l | tr -d ' ') Dateien, nichts Privates gefunden."

if [ "$MODE" = "--probe" ]; then
  KEEP=$(mktemp -d)
  cp -R "$TMP"/. "$KEEP"/
  echo "Probe: öffentlicher Stand liegt in $KEEP (nichts committet)."
  exit 0
fi

# Öffentlichen Klon holen oder anlegen (ein ganz leeres Repository lässt sich nicht klonen)
if [ ! -d "$DIR/.git" ]; then
  if ! gh repo clone "$PUBLIC_REPO" "$DIR" -- -q 2>/dev/null; then
    mkdir -p "$DIR"
    git -C "$DIR" init -q -b main
    git -C "$DIR" remote add origin "https://github.com/$PUBLIC_REPO.git"
  fi
fi
if git -C "$DIR" fetch -q origin main 2>/dev/null; then
  git -C "$DIR" checkout -q -B main origin/main
fi

# Inhalt ersetzen: alles außer .git löschen, neuen Stand hineinkopieren
find "$DIR" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$TMP"/. "$DIR"/
git -C "$DIR" add -A
if git -C "$DIR" diff --cached --quiet; then
  echo "Öffentlicher Stand ist schon aktuell."
else
  git -C "$DIR" commit -q -m "PermLens $V" -m "Stand von $(git rev-parse --short HEAD) im privaten Repository."
  echo "Commit im öffentlichen Repository: PermLens $V"
fi
git -C "$DIR" push -q -u origin main
echo "Gepusht: https://github.com/$PUBLIC_REPO ($(git -C "$DIR" rev-parse --short HEAD))"
