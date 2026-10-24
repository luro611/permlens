"""Zwei-Faktor-Anmeldung mit Einmal-Codes aus einer Handy-App (TOTP nach RFC 6238, wie bei Nextcloud).

- Der geheime Schlüssel steht in data/totp.json (Rechte 600). Ohne diese Datei ist die Zwei-Faktor-Anmeldung aus.
  Notausgang bei verlorenem Handy: die Datei im LXC löschen (z. B. /opt/permlens/data/totp.json).
- Einschalten erst, wenn ein richtiger Code aus der App eingegeben wurde (sonst sperrt man sich aus).
- Ein Code gilt nur einmal. Erlaubt sind 30 Sekunden Abweichung der Uhr in jede Richtung.
- Zehn Ersatz-Codes zum Aufschreiben, jeder einmal nutzbar. Gespeichert werden nur ihre Prüfsummen."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

PERIOD = 30
DIGITS = 6
WINDOW = 1  # ein Zeitschritt davor und danach
RECOVERY_COUNT = 10
ISSUER = 'PermLens'


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def code_at(secret, step):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    num = struct.unpack('>I', mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(num % 10 ** DIGITS).zfill(DIGITS)


def match(secret, code, now=None, after=-1):
    """Zeitschritt, zu dem der Code passt (nur Schritte nach after), sonst None."""
    code = ''.join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = int((time.time() if now is None else now) // PERIOD)
    for s in range(step - WINDOW, step + WINDOW + 1):
        if s > after and hmac.compare_digest(code_at(secret, s), code):
            return s
    return None


def uri(secret, label):
    """Inhalt des QR-Codes für die App."""
    return (f'otpauth://totp/{quote(ISSUER)}:{quote(label)}?secret={secret}&issuer={quote(ISSUER)}'
            f'&algorithm=SHA1&digits={DIGITS}&period={PERIOD}')


def qr_svg(text):
    """QR-Code als SVG zum Einbetten. Dunkel auf hell, damit jede App ihn lesen kann (auch im dunklen Farbschema).
    Nur mit viewBox, ohne feste Größe: Die Größe kommt aus dem CSS, und das SVG wird skaliert statt abgeschnitten."""
    import segno
    return segno.make(text, error='m').svg_inline(scale=1, border=4, dark='#242321', light='#ffffff',
                                                  svgclass='pl-qr', omitsize=True)


def _hash(code):
    return hashlib.sha256(''.join(code.split()).replace('-', '').lower().encode()).hexdigest()


def new_recovery_codes():
    """Zehn Ersatz-Codes wie 'k7m2-q9xa'. Zurück kommen die Codes zum Anzeigen und ihre Prüfsummen zum Speichern."""
    abc = 'abcdefghjkmnpqrstuvwxyz23456789'  # ohne leicht verwechselbare Zeichen (0/o, 1/l/i)
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = ''.join(secrets.choice(abc) for _ in range(8))
        codes.append(f'{raw[:4]}-{raw[4:]}')
    return codes, [_hash(c) for c in codes]


class Store:
    """data/totp.json: {'secret', 'active', 'last_step', 'recovery': [Prüfsummen], 'since'}"""

    def __init__(self, data_dir):
        self.file = Path(data_dir) / 'totp.json'
        self._lock = threading.Lock()

    def load(self):
        try:
            d = json.loads(self.file.read_text(encoding='utf-8'))
            return d if isinstance(d, dict) and d.get('secret') else None
        except (OSError, ValueError):
            return None

    def _save(self, d):
        tmp = self.file.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        os.replace(tmp, self.file)

    @property
    def active(self):
        d = self.load()
        return bool(d and d.get('active'))

    def fingerprint(self):
        """Ändert sich beim Ein- und Ausschalten. Fließt in die Anmelde-Cookies ein: alte Anmeldungen enden dann."""
        d = self.load()
        return hashlib.sha256(d['secret'].encode()).digest() if d and d.get('active') else b''

    def start(self):
        """Neuen Schlüssel zum Einrichten anlegen (noch nicht aktiv). Ist schon einer aktiv, bleibt er."""
        with self._lock:
            d = self.load()
            if d and d.get('active'):
                return d['secret']
            secret = new_secret()
            self._save({'secret': secret, 'active': False})
            return secret

    def pending(self):
        d = self.load()
        return d['secret'] if d and not d.get('active') else ''

    def activate(self, code):
        """Mit einem richtigen Code einschalten. Gibt die Ersatz-Codes zurück (nur dieses eine Mal sichtbar)."""
        with self._lock:
            d = self.load()
            if not d or d.get('active'):
                return None
            step = match(d['secret'], code)
            if step is None:
                return None
            codes, hashes = new_recovery_codes()
            self._save({'secret': d['secret'], 'active': True, 'last_step': step, 'recovery': hashes,
                        'since': datetime.now(timezone.utc).isoformat(timespec='seconds')})
            return codes

    def check(self, code):
        """Code aus der App oder Ersatz-Code prüfen. Zurück: 'app', 'ersatz' oder None."""
        with self._lock:
            d = self.load()
            if not d or not d.get('active'):
                return None
            step = match(d['secret'], code, after=d.get('last_step', -1))
            if step is not None:
                d['last_step'] = step  # derselbe Code gilt kein zweites Mal
                self._save(d)
                return 'app'
            h = _hash(code)
            for i, known in enumerate(d.get('recovery', [])):
                if hmac.compare_digest(h, known):
                    del d['recovery'][i]
                    self._save(d)
                    return 'ersatz'
            return None

    def recovery_left(self):
        d = self.load()
        return len(d.get('recovery', [])) if d and d.get('active') else 0

    def since(self):
        d = self.load()
        return (d or {}).get('since', '')

    def new_recovery(self):
        with self._lock:
            d = self.load()
            if not d or not d.get('active'):
                return None
            codes, d['recovery'] = new_recovery_codes()
            self._save(d)
            return codes

    def disable(self):
        with self._lock:
            try:
                self.file.unlink()
            except FileNotFoundError:
                pass
