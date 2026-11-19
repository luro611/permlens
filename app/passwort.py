"""Eigenes Anmelde-Passwort (ab 1.3.0): ändern in den Einstellungen, zurücksetzen mit einem Befehl im Container.

- Ohne data/passwort.json gilt APP_PASSWORD aus der Stack-Datei. Mit eigenem Passwort gilt nur noch dieses.
- Gespeichert wird nur eine Prüfsumme (scrypt mit Salz), nie das Passwort selbst. Rechte 600.
- Zurücksetzen, wenn das Passwort nicht mehr geht (Shell des PermLens-LXC):
      docker exec -it permlens python -m app.passwort              neues Passwort setzen
      docker exec -it permlens python -m app.passwort --zurueck    wieder APP_PASSWORD benutzen
  Das gilt sofort, ohne Neustart. Wer das kann, hat ohnehin vollen Zugriff auf den LXC.
- Ist die Datei da, aber unlesbar oder beschädigt, gilt NICHT still wieder APP_PASSWORD (das könnte genau das
  Passwort sein, das man loswerden wollte). Dann geht keine Anmeldung, bis der Befehl ein neues Passwort setzt.
- Jedes Setzen und Zurücksetzen schreibt einen neuen Zufallswert 'gen'. Er fließt in die Anmelde-Cookies ein:
  Alte Anmeldungen bleiben ungültig, auch wenn später wieder dasselbe Passwort gilt.
- docker exec läuft als root, PermLens als Benutzer 10001. Der Befehl wechselt deshalb vor dem Schreiben auf den
  Besitzer des Daten-Ordners, sonst könnte PermLens die Datei nicht lesen."""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

MIN_LEN = 8
N, R, P = 2 ** 14, 8, 1  # scrypt: braucht etwa 16 MiB und 50 ms je Prüfung
MAXMEM = 64 * 1024 * 1024

NONE, OWN, BROKEN = 'app_password', 'eigenes', 'kaputt'


def _derive(pw, salt, n=N, r=R, p=P):
    return hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM, dklen=32)


def make_hash(pw):
    salt = secrets.token_bytes(16)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f'scrypt${N}${R}${P}${b64(salt)}${b64(_derive(pw, salt))}'


def verify(pw, stored):
    try:
        kind, n, r, p, salt, dk = stored.split('$')
        if kind != 'scrypt':
            return False
        return hmac.compare_digest(_derive(pw, base64.b64decode(salt), int(n), int(r), int(p)), base64.b64decode(dk))
    except (ValueError, AttributeError):
        return False


class Store:
    """data/passwort.json: {'hash', 'since', 'gen'} mit eigenem Passwort, {'gen'} nach dem Zurücksetzen."""

    def __init__(self, data_dir):
        self.file = Path(data_dir) / 'passwort.json'
        self._lock = threading.Lock()

    def state(self):
        """(NONE | OWN | BROKEN, Inhalt). Nur eine fehlende Datei oder ein Zurücksetzen bedeutet APP_PASSWORD."""
        try:
            d = json.loads(self.file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return NONE, {}
        except (OSError, ValueError):
            return BROKEN, {}
        if not isinstance(d, dict) or not isinstance(d.get('gen'), str):
            return BROKEN, {}
        if 'hash' not in d:
            return NONE, d
        return (OWN, d) if isinstance(d['hash'], str) and d['hash'].startswith('scrypt$') else (BROKEN, {})

    @property
    def active(self):
        """Eigenes Passwort (oder beschädigte Datei): APP_PASSWORD gilt nicht."""
        return self.state()[0] != NONE

    @property
    def broken(self):
        return self.state()[0] == BROKEN

    def since(self):
        st, d = self.state()
        return d.get('since', '') if st == OWN else ''

    def cookie_key(self, app_password):
        """Teil des Cookie-Schlüssels. Ändert sich bei jedem Setzen und Zurücksetzen: alte Anmeldungen enden."""
        st, d = self.state()
        if st == BROKEN:
            return b'kaputt|' + secrets.token_bytes(16)  # niemand ist angemeldet
        if st == OWN:
            return hashlib.sha256(f"{d['hash']}|{d['gen']}".encode()).digest()
        base = hashlib.sha256(app_password.encode()).digest()
        return base + b'|' + d['gen'].encode() if d else base  # ohne Datei wie bis 1.2.0

    def check(self, pw):
        st, d = self.state()
        return st == OWN and verify(pw or '', d['hash'])

    def _write(self, data):
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=self.file.parent, prefix='.passwort-', suffix='.tmp')  # 600, O_EXCL
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

    def set(self, pw):
        self._write({'hash': make_hash(pw), 'since': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                     'gen': secrets.token_hex(16)})

    def clear(self):
        """Wieder APP_PASSWORD. Die Datei bleibt mit neuem 'gen', damit alte Anmeldungen nicht wieder aufleben."""
        self._write({'gen': secrets.token_hex(16)})


def drop_root(data_dir):
    """Als root (docker exec) auf den Besitzer des Daten-Ordners wechseln, bevor etwas geschrieben wird."""
    if os.geteuid() != 0:
        return
    st = os.stat(data_dir)
    if st.st_uid == 0:
        return
    os.setgroups([])
    os.setgid(st.st_gid)
    os.setuid(st.st_uid)


def _audit(target):
    """Ins Protokoll von PermLens, wenn es die Datenbank schon gibt (sonst legt der Befehl keine an)."""
    from . import config, db
    if not (config.DATA / 'permlens.db').exists():
        return
    try:
        db.audit('passwort', target=target, result='ok', client='befehl')
    except Exception:
        pass


def main(argv=None, ask=getpass.getpass):
    from . import config, totp
    args = sys.argv[1:] if argv is None else argv
    if args and args not in (['--zurueck'], ['--reset']):
        print('Aufruf / usage: python -m app.passwort [--zurueck]')
        return 2
    if not config.DATA.is_dir():
        print(f'Daten-Ordner fehlt / data folder missing: {config.DATA}')
        return 1
    drop_root(config.DATA)
    store = Store(config.DATA)
    if args:
        store.clear()
        _audit('zurücksetzen auf APP_PASSWORD')
        print('Eigenes Passwort gelöscht, es gilt wieder APP_PASSWORD. Alle Browser sind abgemeldet. / '
              'Own password removed, APP_PASSWORD applies again. All browsers are signed out.')
        return 0
    pw = ask('Neues Passwort / new password: ')
    if len(pw) < MIN_LEN:
        print(f'Zu kurz, mindestens {MIN_LEN} Zeichen. Nichts geändert. / Too short, at least {MIN_LEN} characters. Nothing changed.')
        return 1
    if ask('Noch einmal / once more: ') != pw:
        print('Die Eingaben sind verschieden. Nichts geändert. / The entries differ. Nothing changed.')
        return 1
    store.set(pw)
    _audit('befehl')
    print('Passwort gesetzt, es gilt sofort. Alle Browser sind abgemeldet. / Password set, effective now. All browsers are signed out.')
    print('Nach Fehlversuchen kann die Anmeldung noch bis zu 5 Minuten gesperrt sein. / After failed attempts, sign-in may stay locked for up to 5 minutes.')
    if totp.Store(config.DATA).active:
        print('Die Zwei-Faktor-Anmeldung bleibt eingeschaltet. / Two-factor sign-in stays on.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
