"""Einrichtung mit einem einzigen Befehl auf dem Proxmox-Host.

PermLens zeigt einen Befehl (siehe command()), der ein kleines Script von http://<PermLens>/setup/<Einmal-Code> lädt,
seine SHA-256-Prüfsumme vergleicht und es nur dann ausführt. Die Prüfsumme steht im Befehl, der Befehl kommt über
den Browser. Wer das Script unterwegs zum Proxmox austauscht, fällt also auf. Das Script (siehe script())
  1. das Wächter-Script installiert und seinen Fingerabdruck prüft,
  2. den Schlüssel von PermLens in /root/.ssh/authorized_keys einträgt (gebunden an Wächter und LXC-Adresse),
  3. PermLens zurückmeldet, unter welcher Adresse und mit welchem Host-Schlüssel der Proxmox erreichbar ist.
Der Einmal-Code gilt eine Stunde und nur für eine Einrichtung.

Läuft PermLens über HTTPS (eigenes Zertifikat, siehe tls.py), legen alle curl-Aufrufe den Schlüssel dieses
Zertifikats fest (--pinnedpubkey). Proxmox lädt dann nur von genau diesem PermLens, auch ohne Zertifizierungsstelle."""
import hashlib
import hmac
import re
import secrets
import time

from . import db, tls
from .pve import ssh

VALID_SECONDS = 60 * 60
TOKEN = re.compile(r'^[0-9a-f]{32}$')
ORIGIN = re.compile(r'^https?://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:[0-9]{1,5})?$')
HOSTKEY = re.compile(r'^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]{20,800}$')


def token():
    """Gültigen Einmal-Code holen oder neu anlegen."""
    tok, created = db.get_setting('setup_token'), db.get_setting('setup_created', '0')
    if not TOKEN.match(tok or '') or time.time() - float(created or 0) > VALID_SECONDS:
        tok = secrets.token_hex(16)
        db.set_settings(setup_token=tok, setup_created=str(time.time()))
    return tok


def renew():
    db.set_settings(setup_token='', setup_created='0')
    return token()


def check(tok):
    cur = db.get_setting('setup_token')
    fresh = time.time() - float(db.get_setting('setup_created', '0') or 0) <= VALID_SECONDS
    return bool(TOKEN.match(tok or '')) and bool(cur) and fresh and hmac.compare_digest(tok, cur)


def pending():
    """True, solange ein Einrichtungs-Befehl gültig und noch nicht benutzt ist."""
    return check(db.get_setting('setup_token'))


def used():
    db.set_settings(setup_token='', setup_created='0')


def valid_origin(origin):
    """Adresse von PermLens (aus der Anfrage). Landet im Bash-Script, deshalb nur einfache Zeichen."""
    return bool(ORIGIN.match(origin or ''))


def curl_opts(origin):
    """Zusätzliche curl-Schalter: bei HTTPS nur dieses Zertifikat akzeptieren (Pin), nie zurück auf HTTP."""
    p = tls.pin()
    if origin.startswith('https://') and p:
        return f'--proto \'=https\' -k --pinnedpubkey "sha256//{p}" '
    return ''


def command(origin, tok, guard_sha):
    """Befehl für die Proxmox-Shell: Script laden, Prüfsumme vergleichen, erst dann ausführen."""
    if not valid_origin(origin):
        return 'echo "PermLens: Ungültige Adresse. PermLens bitte über die IP-Adresse oder einen einfachen Namen öffnen."'
    sha = hashlib.sha256(script(origin, tok, guard_sha).encode()).hexdigest()
    return (f'f=$(mktemp) && if curl -fsSL {curl_opts(origin)}{origin}/setup/{tok} -o "$f" && echo "{sha}  $f" | sha256sum -c --status; '
            'then bash "$f"; else echo "PermLens: Befehl abgelaufen oder unterwegs verändert, nichts ausgeführt." >&2; '
            'fi; rm -f "$f"')


def script(origin, tok, guard_sha):
    """Bash-Script für den Proxmox-Host. Alle Werte stammen von PermLens selbst oder sind streng geprüft."""
    if not valid_origin(origin) or not TOKEN.match(tok or '') or not re.fullmatch(r'[0-9a-f]{64}', guard_sha):
        raise ValueError('ungültige Werte für das Einrichtungs-Script')
    pub = ssh.public_key()
    return f'''#!/bin/bash
# PermLens – Einrichtung auf dem Proxmox-Host (https://github.com/luro611/permlens)
set -euo pipefail
PL="{origin}"
CODE="{tok}"
GUARD=/usr/local/sbin/permlens-guard
KEYS=/root/.ssh/authorized_keys
fehler() {{ echo "PermLens: $*" >&2; exit 1; }}

[ "$(id -u)" = 0 ] || fehler "Bitte als root ausführen (Proxmox-Weboberfläche → Knoten → Shell)."
command -v pct >/dev/null || fehler "Das ist kein Proxmox-Host (pct fehlt)."

echo "1/3 Wächter-Script installieren …"
curl -fsSL {curl_opts(origin)}"$PL/host/permlens-guard" -o "$GUARD.neu"
echo "{guard_sha}  $GUARD.neu" | sha256sum -c --quiet - || {{ rm -f "$GUARD.neu"; fehler "Wächter-Script beschädigt, Abbruch."; }}
chmod 755 "$GUARD.neu" && mv "$GUARD.neu" "$GUARD"

echo "2/3 Schlüssel von PermLens erlauben …"
PL_HOST="${{PL#*://}}"; PL_HOST="${{PL_HOST%%/*}}"; PL_HOST="${{PL_HOST%:*}}"
PL_IP=$(getent ahostsv4 "$PL_HOST" | awk 'NR==1{{print $1}}')
[ -n "$PL_IP" ] || fehler "Adresse von PermLens ($PL_HOST) nicht gefunden."
KEY="{pub}"
mkdir -p /root/.ssh && touch "$KEYS"
# Nur ergänzen, nie etwas löschen. Eine schon vorhandene Zeile mit demselben Schlüssel bleibt, wie sie ist.
if grep -qF "$KEY" "$KEYS"; then
  echo "   Der Schlüssel ist schon eingetragen."
else
  echo "command=\\"$GUARD\\",restrict,from=\\"$PL_IP\\" $KEY" >> "$KEYS"
fi

echo "3/3 PermLens Bescheid geben …"
HOST_IP=$(ip -4 route get "$PL_IP" | awk '{{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}}' | head -1)
PORT=$(sshd -T 2>/dev/null | awk '/^port /{{print $2; exit}}'); PORT=${{PORT:-22}}
HOSTKEY=$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)
curl -fsS {curl_opts(origin)}-X POST "$PL/setup/$CODE/fertig" \\
  --data-urlencode "host=$HOST_IP" --data-urlencode "port=$PORT" \\
  --data-urlencode "node=$(hostname)" --data-urlencode "lxc_ip=$PL_IP" --data-urlencode "hostkey=$HOSTKEY"
echo
'''


def finish(host, port, node, lxc_ip, hostkey):
    """Rückmeldung des Hosts speichern. Gibt eine Fehlermeldung zurück oder ''."""
    if not ssh.valid_host(host) or not ssh.valid_host(lxc_ip):
        return 'Ungültige Adresse.'
    if not str(port).isdigit() or not 0 < int(port) < 65536:
        return 'Ungültiger Port.'
    if not HOSTKEY.match(hostkey or ''):
        return 'Ungültiger Host-Schlüssel.'
    node = re.sub(r'[^A-Za-z0-9.-]', '', node or '')[:63]
    ssh.trust_host(host, int(port), hostkey)
    # Weiterer Proxmox: kommt dazu. Derselbe Proxmox noch einmal (gleiche Adresse und Port): wird aktualisiert.
    hid = db.add_host(host, int(port), node=node, lxc_ip=lxc_ip)
    db.set_settings(setup_last_host=str(hid), lxc_ip=lxc_ip)
    used()
    return ''
