"""HTTPS mit eigenem Zertifikat (0.2.2): Zertifikat, Pin im Einrichtungs-Befehl, Umleitung, sicheres Cookie."""
import asyncio
import subprocess

import pytest

from app import setup, tls
from app.serve import redirect_app


@pytest.fixture
def mit_tls(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, '_dir', lambda: tmp_path / 'tls')
    tls.ensure()
    return tmp_path


def test_zertifikat_und_pin(mit_tls):
    key, cert, _ = tls.paths()
    assert tls.enabled() and (key.stat().st_mode & 0o777) == 0o600
    assert tls.PIN_OK.match(tls.pin())
    assert len(tls.fingerprint().split(':')) == 32
    before = tls.pin()
    tls.ensure()  # vorhandenes Zertifikat bleibt
    assert tls.pin() == before


def test_einrichtung_mit_pin(mit_tls, client):
    from app.pve import ssh
    ssh.generate_key()
    sha = '0' * 64
    cmd = setup.command('https://192.168.1.50:8443', 'a' * 32, sha)
    assert ("--proto '=https' -k --pinnedpubkey \"sha256//" + tls.pin() + '" https://192.168.1.50:8443/setup/') in cmd
    s = setup.script('https://192.168.1.50:8443', 'a' * 32, sha)
    assert s.count('--pinnedpubkey') == 2
    assert subprocess.run(['bash', '-n'], input=s, text=True).returncode == 0
    assert '--pinnedpubkey' not in setup.command('http://192.168.1.50', 'a' * 32, sha)  # ohne HTTPS wie bisher


def _call(app, path, host=b'192.168.1.50', qs=b''):
    sent = []

    async def send(m):
        sent.append(m)
    asyncio.run(app({'type': 'http', 'path': path, 'query_string': qs, 'headers': [(b'host', host)]}, None, send))
    return sent[0]['status'], dict(sent[0]['headers'])


def test_umleitung():
    app = redirect_app('443')
    assert _call(app, '/settings', qs=b'a=1') == (308, {b'location': b'https://192.168.1.50/settings?a=1', b'content-length': b'0'})
    assert _call(redirect_app('8443'), '/', host=b'192.168.1.50:8000')[1][b'location'] == b'https://192.168.1.50:8443/'
    assert _call(app, '/healthz')[0] == 200
    assert _call(app, '/', host=b'evil.example/@x')[1][b'location'] == b'https://localhost/'


def test_hinweis_bei_http_und_sicheres_cookie(mit_tls, client):
    r = client.get('/settings')
    assert 'nicht verschlüsselt' in r.text and 'HTTPS-Zertifikat dieses PermLens' in r.text
    from app.main import app
    from fastapi.testclient import TestClient
    https = TestClient(app, base_url='https://testserver')
    r = https.post('/login', data={'password': 'test-passwort-123', 'next': '/'}, follow_redirects=False)
    assert 'secure' in r.headers.get('set-cookie', '').lower()
