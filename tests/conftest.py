"""Testumgebung: eigener Datenordner und ein Test-Passwort, bevor die App geladen wird."""
import os
import tempfile

os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='permlens-test-')
os.environ['APP_PASSWORD'] = 'test-passwort-123'
os.environ['UPDATE_CHECK'] = '0'  # Tests fragen nie bei GitHub nach (einzelne Tests schalten es gezielt ein)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def anonym():
    """Client ohne Anmeldung, mit frischer Fehlversuch-Zählung."""
    from app.main import SEC, app
    SEC._fails.clear()
    return TestClient(app)


@pytest.fixture
def client(anonym):
    """Angemeldeter Client."""
    r = anonym.post('/login', data={'password': os.environ['APP_PASSWORD'], 'next': '/'}, follow_redirects=False)
    assert r.status_code == 303
    return anonym


@pytest.fixture(autouse=True)
def scan_sofort(monkeypatch):
    """In Tests läuft der Scan nicht im Hintergrund, sondern sofort (sonst hängt das Ergebnis vom Timing ab)."""
    from app.pve import scan

    def start(host, port=22, on_done=None, host_id=None):
        result = scan.run(host, port, host_id)
        if on_done:
            on_done(result)
        return True
    monkeypatch.setattr(scan, 'start', start)


# Bis 0.4.x stand die Verbindung in settings (pve_host, pve_write …), seit 0.5.0 in der Tabelle hosts.
# Die Tests setzen sie weiter mit den alten Namen; set_pve legt daraus den (einzigen) Host an oder ändert ihn.
OLD = {'pve_host': 'host', 'pve_port': 'port', 'pve_node': 'node', 'pve_guard': 'guard', 'pve_write': 'write_ids',
       'pve_connected': 'connected', 'lxc_ip': 'lxc_ip'}


def set_pve(**kw):
    from contextlib import closing
    from app import db
    if 'lxc_ip' in kw:
        db.set_settings(lxc_ip=kw['lxc_ip'])
    f = {OLD[k]: v for k, v in kw.items() if k in OLD}
    if 'connected' in f:
        f['connected'] = 1 if f['connected'] == '1' else 0
    if 'port' in f:
        f['port'] = int(f['port'] or 22)
    h = db.active_host()
    if 'host' in f and (not h or h['host'] != f['host']):
        with closing(db.connect()) as c, c:
            c.execute('DELETE FROM scans')
            c.execute('DELETE FROM hosts')
        if f['host']:
            db.add_host(f.pop('host'), f.pop('port', 22), **f)
        return
    f.pop('host', None)
    if h:
        db.update_host(h['id'], **f)


def get_pve(key):
    from app import db
    h = db.active_host() or {}
    return str(h.get(OLD[key], '') if key != 'pve_connected' else ('1' if h.get('connected') else '0'))


def host_id():
    """id des aktiven Hosts, wie sie die Vorschau ins Formular schreibt."""
    from app import db
    return str((db.active_host() or {}).get('id', ''))
