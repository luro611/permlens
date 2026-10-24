# Basis-Image fest per Digest (nicht nur per Tag). Aktualisieren: Digest mit
#   docker buildx imagetools inspect python:3.12-slim
# abfragen, hier eintragen, bauen und testen.
FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
LABEL org.opencontainers.image.title="PermLens" \
      org.opencontainers.image.description="Rechte-Manager für LXC-Container (derzeit für Proxmox VE)" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/luro611/permlens"
ENV PYTHONUNBUFFERED=1 PORT=8000 TLS_PORT=8443 DATA_DIR=/app/data
WORKDIR /app
# openssh-client: PermLens spricht per SSH mit dem Proxmox-Host. openssl: eigenes HTTPS-Zertifikat beim ersten Start
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client openssl tzdata && rm -rf /var/lib/apt/lists/*
# Eigener Benutzer: PermLens läuft nicht als root (UID/GID 10001, fest, damit der Daten-Ordner passt)
RUN groupadd --system --gid 10001 permlens \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app/data --no-create-home --shell /usr/sbin/nologin permlens
COPY requirements.txt .
# Nur Pakete mit genau den Prüfsummen aus requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY app ./app
COPY static ./static
COPY host ./host
COPY docker/entrypoint.sh /usr/local/bin/permlens-start
COPY VERSION LICENSE CHANGELOG.md ./
RUN chmod 755 /usr/local/bin/permlens-start && mkdir -p /app/data && chown permlens:permlens /app/data
EXPOSE 8000 8443
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8000'),timeout=4)"
ENTRYPOINT ["/usr/local/bin/permlens-start"]
