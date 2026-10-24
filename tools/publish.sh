#!/bin/sh
# PermLens-Image veröffentlichen (nach dem Vorbild von MediaDB). Auf dem Mac im Projektordner ausführen:
#     sh tools/publish.sh dev        Test-Image ghcr.io/luro611/permlens:dev hochladen (kein Tag, kein Release)
#     sh tools/publish.sh            Version aus VERSION veröffentlichen: Image (<Version> und latest), Git-Tag, Release
#     sh tools/publish.sh release    nur Tag und Release (Image ist schon oben)
#
# Zwei Repositorys (Weg A, ab 1.0): Entwickelt wird im privaten luro611/permlens-dev. Zeigt origin dorthin,
# exportiert das Skript zuerst den öffentlichen Stand nach luro611/permlens (tools/export-oeffentlich.sh), baut das
# Image aus genau diesem Stand und legt Tag und Release im öffentlichen Repository an. Zeigt origin noch auf
# luro611/permlens (vor dem Umbenennen), läuft alles wie bisher in diesem einen Repository.
#
# Baut für amd64 (PC, Server, Proxmox) und arm64 (Raspberry Pi, Mac), mit SBOM und Herkunftsnachweis.
# Einmalig vorher: gh auth login  und  gh auth refresh --scopes write:packages
set -e
cd "$(dirname "$0")/.."
USER_NAME=${GITHUB_USER:-luro611}
REPO=$USER_NAME/permlens            # öffentlich: Image, Tags, Releases, Update-Hinweis
DEV_REPO=$USER_NAME/permlens-dev    # privat: Entwicklung mit Planung und Testumgebung
IMAGE=ghcr.io/$REPO
PUBLIC_DIR=${PUBLIC_DIR:-../permlens-oeffentlich}
export PUBLIC_DIR
V=$(cat VERSION)
TAG=v$V
MODE=${1:-}

command -v gh >/dev/null || { echo "Abbruch: Das GitHub-Programm gh fehlt (brew install gh, dann gh auth login)."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Abbruch: gh ist nicht bei GitHub angemeldet (gh auth login)."; exit 1; }

case "$(git remote get-url origin)" in
  *"/$DEV_REPO.git"|*"/$DEV_REPO"|*":$DEV_REPO.git") SPLIT=1 ;;
  *) SPLIT=0 ;;
esac

# Nur veröffentlichen, was auch auf GitHub liegt: keine offenen Änderungen, alles gepusht
if [ -n "$(git status --porcelain)" ]; then
  echo "Abbruch: Es gibt noch nicht committete Änderungen (git status)."; exit 1
fi
git fetch -q origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "Abbruch: Der aktuelle Stand ist noch nicht zu GitHub gepusht (git push)."; exit 1
fi

build() {  # build <Ordner> <Commit> <tag> [<tag> …]
  SRC=$1; REV=$2; shift 2
  gh auth token | docker login ghcr.io -u "$USER_NAME" --password-stdin >/dev/null \
    || { echo "Abbruch: Anmeldung bei ghcr.io fehlgeschlagen. Fehlt die Berechtigung? gh auth refresh --scopes write:packages"; exit 1; }
  TAGS=""
  for t in "$@"; do TAGS="$TAGS -t $IMAGE:$t"; done
  echo "Baue $IMAGE ($*) für amd64 + arm64 aus $SRC …"
  docker buildx inspect permlens-builder >/dev/null 2>&1 || docker buildx create --name permlens-builder --driver docker-container >/dev/null
  # shellcheck disable=SC2086
  docker buildx build --builder permlens-builder \
    --platform linux/amd64,linux/arm64 \
    --label "org.opencontainers.image.source=https://github.com/$REPO" \
    --label "org.opencontainers.image.version=$V" \
    --label "org.opencontainers.image.revision=$REV" \
    --sbom=true --provenance=mode=max \
    $TAGS --push "$SRC"
  # SBOM (Liste aller Pakete im Image) und Herkunftsnachweis (welcher Commit, welcher Build) hängen am Image.
  # Ansehen: docker buildx imagetools inspect $IMAGE:<tag> --format '{{ json .SBOM }}' bzw. '{{ json .Provenance }}'
  echo "Image fertig: $IMAGE ($*)"
}

if [ "$MODE" = "dev" ]; then
  build . "$(git rev-parse HEAD)" dev
  echo
  echo "Im LXC (Dockhand): Stack permlens → Pull und Redeploy."
  exit 0
fi

case "$V" in *-*) echo "Abbruch: VERSION ist $V (Vorabversion). Für ein Release erst VERSION anpassen, zum Testen: sh tools/publish.sh dev"; exit 1;; esac
if ! grep -q "^## PermLens $V " CHANGELOG.md; then
  echo "Abbruch: In CHANGELOG.md fehlt der Abschnitt „## PermLens $V – …“."; exit 1
fi
if [ "$MODE" != "release" ] && git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
   && [ "$(git rev-parse "$TAG^{commit}")" != "$(git rev-parse HEAD)" ]; then
  echo "Abbruch: Den Tag $TAG gibt es schon, aber für einen anderen Stand. VERSION hochzählen?"; exit 1
fi
TAG_MSG=$(grep -m1 "^## PermLens $V " CHANGELOG.md | sed 's/^## //')

# Tag im privaten Repository: merkt sich, aus welchem Entwicklungsstand die Version kam
if ! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  git tag -a "$TAG" -m "$TAG_MSG"
fi

if [ "$SPLIT" = 1 ]; then
  sh tools/export-oeffentlich.sh
  SRC=$PUBLIC_DIR
  REV=$(git -C "$SRC" rev-parse HEAD)
  if git -C "$SRC" rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
     && [ "$(git -C "$SRC" rev-parse "$TAG^{commit}")" != "$REV" ]; then
    echo "Abbruch: Den Tag $TAG gibt es im öffentlichen Repository schon für einen anderen Stand."; exit 1
  fi
else
  SRC=.
  REV=$(git rev-parse HEAD)
fi

[ "$MODE" = "release" ] || build "$SRC" "$REV" "$V" latest

git push -q origin "refs/tags/$TAG"
if [ "$SPLIT" = 1 ]; then
  git -C "$SRC" rev-parse -q --verify "refs/tags/$TAG" >/dev/null || git -C "$SRC" tag -a "$TAG" -m "$TAG_MSG"
  git -C "$SRC" push -q origin "refs/tags/$TAG"
fi
echo "Tag $TAG ist auf GitHub ($REPO$([ "$SPLIT" = 1 ] && echo " und $DEV_REPO"))."

if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo "Das Release $TAG gibt es schon: https://github.com/$REPO/releases/tag/$TAG"
  exit 0
fi
NOTES=$(mktemp)
TITLE=$(python3 - "$V" "$NOTES" <<'EOF'
import re, sys
v, out = sys.argv[1], sys.argv[2]
text = open('CHANGELOG.md', encoding='utf-8').read()
m = re.search(r'^## (PermLens ' + re.escape(v) + r' [^\n]*)\n(.*?)(?=^#{1,2} |^---|\Z)', text, re.M | re.S)
open(out, 'w', encoding='utf-8').write(m.group(2).strip() + '\n')
print(m.group(1).strip())
EOF
)
gh release create "$TAG" -R "$REPO" --verify-tag --latest --title "$TITLE" --notes-file "$NOTES" "$SRC/docker-compose.homelab.yml"
rm -f "$NOTES"
echo "Release angelegt: https://github.com/$REPO/releases/tag/$TAG"
echo
echo "Im LXC (Dockhand): Stack permlens → Pull und Redeploy."
