"""Zugriffsschutz (nach dem Vorbild von MediaDB, aber strenger).

- Heimnetz: Ohne ALLOW_PUBLIC=1 werden Anfragen von öffentlichen IP-Adressen abgewiesen.
- Passwort ist Pflicht: Ohne APP_PASSWORD (mindestens 8 Zeichen) zeigt PermLens nur einen Hinweis und sonst nichts.
- Anmeldung per Cookie, das mit dem Browser endet (ab 0.5.4; höchstens 7 Tage). Ein neues Passwort meldet alle ab.
- Zwei-Faktor-Anmeldung (ab 0.5.2, wahlweise): Nach dem Passwort ein Code aus der Handy-App (siehe totp.py).
  Der Code gilt in diesem Browser bis 24:00 Uhr (Zeitzone TZ), danach braucht es einen neuen, auch mitten in
  einer Sitzung. Ein- oder Ausschalten meldet alle ab.
- Nach 5 Fehlversuchen von derselben Adresse ist die Anmeldung dort 5 Minuten gesperrt."""
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote

from . import totp

COOKIE = 'permlens_auth'
MAX_AGE = 60 * 60 * 24 * 7
# Zwischenschritt: Passwort stimmt, der Code aus der App fehlt noch
STEP_COOKIE = 'permlens_2fa'
STEP_AGE = 5 * 60
# Code aus der App ist heute in diesem Browser schon eingegeben worden (gilt bis 24:00 Uhr)
DAY_COOKIE = 'permlens_2fa_tag'
MIN_LEN = 8
MAX_FAILS = 5
LOCK_SECONDS = 5 * 60
# /setup/…: Einrichtungs-Script und Rückmeldung vom Proxmox-Host (geschützt durch den Einmal-Code)
OPEN_PATHS = ('/login', '/static/', '/healthz', '/lang/', '/host/permlens-guard', '/setup/')


def _flag(name):
    return os.getenv(name, '0').strip().lower() in ('1', 'true', 'yes', 'ja', 'on')


class Settings:
    def __init__(self, data_dir):
        self.allow_public = _flag('ALLOW_PUBLIC')
        self.password = os.getenv('APP_PASSWORD', '')
        self.data_dir = Path(data_dir)
        self._secret = None
        self._fails = {}
        self._lock = threading.Lock()
        self.totp = totp.Store(self.data_dir)

    @property
    def password_set(self):
        return len(self.password) >= MIN_LEN

    def secret(self):
        """Geheimer Schlüssel für die Cookies, beim ersten Start in data/secret.key angelegt."""
        if self._secret is None:
            f = self.data_dir / 'secret.key'
            try:
                self._secret = f.read_bytes().strip()
            except OSError:
                self._secret = b''
            if not self._secret:
                self._secret = secrets.token_hex(32).encode()
                f.write_bytes(self._secret)
                os.chmod(f, 0o600)
        return self._secret

    def _sig(self, exp, kind='auth'):
        key = self.secret() + b'|' + hashlib.sha256(self.password.encode()).digest()
        if fp := self.totp.fingerprint():
            key += b'|' + fp
        # 'sitzung' statt 'auth' (ab 0.5.4): Die alten 7-Tage-Cookies gelten nicht mehr, sonst überleben sie den Browser
        msg = f"{'sitzung' if kind == 'auth' else kind}|{exp}"
        return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()

    def make_token(self, kind='auth', age=MAX_AGE, until=None):
        exp = int(until if until else time.time() + age)
        return f'{exp}.{self._sig(exp, kind)}'

    def token_ok(self, tok, kind='auth'):
        try:
            exp, sig = (tok or '').split('.', 1)
            return int(exp) > time.time() and hmac.compare_digest(sig, self._sig(int(exp), kind))
        except (ValueError, TypeError):
            return False

    def make_step_token(self):
        return self.make_token('2fa', STEP_AGE)

    def step_ok(self, tok):
        return self.token_ok(tok, '2fa')

    def make_day_token(self):
        return self.make_token('tag', until=end_of_day())

    def day_ok(self, tok):
        return self.token_ok(tok, 'tag')

    def session_until(self):
        """Ablauf einer neuen Anmeldung: mit Zwei-Faktor um 24:00 Uhr, sonst nach 7 Tagen."""
        return end_of_day() if self.totp.active else int(time.time()) + MAX_AGE

    def password_ok(self, pw):
        a = hashlib.sha256((pw or '').encode()).digest()
        b = hashlib.sha256(self.password.encode()).digest()
        return self.password_set and hmac.compare_digest(a, b)

    # ---- Sperre nach Fehlversuchen
    def locked_for(self, client):
        """Sekunden, die die Adresse noch gesperrt ist (0 = nicht gesperrt)."""
        with self._lock:
            n, until = self._fails.get(client, (0, 0))
            return max(0, int(until - time.time())) if n >= MAX_FAILS else 0

    def failed(self, client):
        with self._lock:
            n, until = self._fails.get(client, (0, 0))
            if n >= MAX_FAILS and until <= time.time():
                n = 0  # Sperre abgelaufen, neu zählen
            n += 1
            self._fails[client] = (n, time.time() + LOCK_SECONDS if n >= MAX_FAILS else 0)
            return n

    def succeeded(self, client):
        with self._lock:
            self._fails.pop(client, None)


def end_of_day(now=None):
    """Nächste Mitternacht in der Zeitzone des Containers (TZ) als Unix-Zeit (mktime beachtet die Sommerzeit)."""
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1)))


def is_local(host):
    """Heimnetz, eigener Rechner und VPN (z. B. Tailscale) zählen als lokal, alles Öffentliche nicht."""
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host.split('%')[0])
    except ValueError:
        return True  # z. B. Testclient
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return not ip.is_global


def _cookie(headers, name):
    for k, v in headers:
        if k == b'cookie':
            for part in v.decode('latin-1').split(';'):
                if '=' in part:
                    a, b = part.strip().split('=', 1)
                    if a == name:
                        return b
    return None


def _page(title_de, text_de, title_en, text_en):
    return ('<!doctype html><meta charset="utf-8"><title>PermLens</title>'
            '<body style="font-family:sans-serif;max-width:40em;margin:3em auto;line-height:1.5">'
            f'<h1>{title_de}</h1><p>{text_de}</p><h1 lang="en">{title_en}</h1><p lang="en">{text_en}</p>'
            '</body>').encode()


BLOCKED = _page('Kein Zugriff aus dem Internet',
                'PermLens ist nur für das eigene Heimnetz gedacht. Zugriffe von öffentlichen Adressen sind gesperrt.',
                'No access from the internet',
                'PermLens is meant for your home network only. Requests from public addresses are blocked.')
NO_PASSWORD = _page('Kein Passwort gesetzt',
                    f'PermLens braucht ein Passwort mit mindestens {MIN_LEN} Zeichen. Trage es in Dockhand bei den '
                    'Variablen des Stacks „permlens“ ein (Name <code>APP_PASSWORD</code>) und starte den Stack neu.',
                    'No password set',
                    f'PermLens needs a password with at least {MIN_LEN} characters. Add it in Dockhand as a variable of the '
                    '“permlens” stack (name <code>APP_PASSWORD</code>) and restart the stack.')


class Gate:
    """ASGI-Middleware: Heimnetz prüfen, Passwort-Pflicht prüfen, Anmeldung prüfen."""

    def __init__(self, app, settings):
        self.app = app
        self.s = settings

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '/')
        client = (scope.get('client') or (None,))[0]
        html = [(b'content-type', b'text/html; charset=utf-8')]

        if not self.s.allow_public and not is_local(client):
            return await _respond(send, 403, BLOCKED, html)
        if path.startswith(('/static/', '/healthz')):
            return await self.app(scope, receive, send)
        if not self.s.password_set:
            return await _respond(send, 503, NO_PASSWORD, html)
        if not path.startswith(OPEN_PATHS) and not self.s.token_ok(_cookie(scope.get('headers') or [], COOKIE)):
            qs = scope.get('query_string', b'').decode('latin-1')
            nxt = path + ('?' + qs if qs else '')
            return await _respond(send, 303, b'', [(b'location', f'/login?next={quote(nxt)}'.encode())])
        return await self.app(scope, receive, send)


async def _respond(send, status, body, headers):
    await send({'type': 'http.response.start', 'status': status,
                'headers': headers + [(b'content-length', str(len(body)).encode())]})
    await send({'type': 'http.response.body', 'body': body})
