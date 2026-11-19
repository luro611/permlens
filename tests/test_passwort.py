"""Eigenes Passwort (ab 1.3.0): ändern in den Einstellungen, zurücksetzen mit dem Befehl im Container."""
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import config, db, passwort

ALT = os.environ['APP_PASSWORD']
NEU = 'ab$cd#ef "1 '  # genau die Zeichen, die in einer .env-Datei verloren gehen


@pytest.fixture(autouse=True)
def sauber():
    from app.main import SEC
    SEC.own.file.unlink(missing_ok=True)
    yield
    SEC.own.file.unlink(missing_ok=True)


def anmelden(c, pw):
    return c.post('/login', data={'password': pw, 'next': '/'}, follow_redirects=False)


def aendern(c, current=ALT, new=NEU, repeat=None):
    return c.post('/settings/password', data={'current': current, 'new': new, 'repeat': new if repeat is None else repeat},
                  follow_redirects=False)


def test_pruefsumme():
    h = passwort.make_hash(NEU)
    assert NEU not in h and passwort.verify(NEU, h) and not passwort.verify('falsch', h)
    assert h != passwort.make_hash(NEU)  # eigenes Salz
    assert not passwort.verify(NEU, 'kaputt') and not passwort.verify(NEU, 'md5$1$1$1$AA==$AA==')


def test_aendern(client):
    r = aendern(client)
    assert r.status_code == 303 and 'message=' in r.headers['location']
    assert db.audit_entries(1)[0]['action'] == 'passwort'
    assert client.get('/settings').status_code == 200  # dieser Browser bleibt angemeldet

    from app.main import SEC, app
    SEC._fails.clear()
    neu = TestClient(app)
    assert anmelden(neu, ALT).status_code == 401  # APP_PASSWORD gilt nicht mehr
    assert anmelden(neu, NEU).status_code == 303
    assert NEU not in (config.DATA / 'passwort.json').read_text()
    assert stat.S_IMODE(os.stat(config.DATA / 'passwort.json').st_mode) == 0o600


def test_aendern_meldet_andere_browser_ab(client):
    from app.main import app
    anderer = TestClient(app)
    assert anmelden(anderer, ALT).status_code == 303
    aendern(client)
    assert anderer.get('/settings', follow_redirects=False).status_code == 303


@pytest.mark.parametrize('kw', [{'current': 'falsch'}, {'new': 'kurz'}, {'repeat': 'etwas-anderes'}])
def test_aendern_abgelehnt(client, kw):
    from app.main import SEC
    r = aendern(client, **kw)
    assert 'err=' in r.headers['location'] and not SEC.own.active


def test_aendern_zaehlt_fehlversuche(client):
    from app import security as sec
    from app.main import SEC
    for _ in range(sec.MAX_FAILS):
        aendern(client, current='falsch')
    aendern(client)  # auch das richtige Passwort hilft während der Sperre nicht
    assert not SEC.own.active


def test_aendern_mit_zwei_faktor_bleibt_angemeldet(client):
    from app import totp
    from app.main import SEC
    import time
    secret = SEC.totp.start()
    SEC.totp.activate(totp.code_at(secret, int(time.time() // totp.PERIOD)))
    try:
        anmelden(client, ALT)  # Code ist heute noch nicht eingegeben: Cookie aus dem Fixture gilt nicht mehr
        client.post('/login/code', data={'code': totp.code_at(secret, int(time.time() // totp.PERIOD) + 1)})
        assert client.get('/settings', follow_redirects=False).status_code == 200
        aendern(client)
        assert client.get('/settings', follow_redirects=False).status_code == 200
        assert anmelden(client, NEU).headers['location'] == '/'  # Tages-Cookie gilt weiter, kein neuer Code nötig
    finally:
        SEC.totp.disable()


def test_befehl_setzt_passwort_und_gilt_ohne_neustart(anonym, capsys):
    eingaben = iter([NEU, NEU])
    assert passwort.main([], ask=lambda _: next(eingaben)) == 0
    assert 'Passwort gesetzt' in capsys.readouterr().out
    assert anmelden(anonym, NEU).status_code == 303


@pytest.mark.parametrize('werte', [['kurz'], ['langes-passwort', 'anderes-passwort']])
def test_befehl_lehnt_ab(werte):
    from app.main import SEC
    eingaben = iter(werte)
    assert passwort.main([], ask=lambda _: next(eingaben)) == 1
    assert not SEC.own.active


def test_befehl_zurueck(anonym):
    from app.main import SEC
    SEC.own.set(NEU)
    assert passwort.main(['--zurueck']) == 0
    assert anmelden(anonym, ALT).status_code == 303


@pytest.mark.parametrize('inhalt', ['{kaputt', '', '[]', '{"hash": "md5$x", "gen": "1"}', '{"hash": "scrypt$1"}'])
def test_datei_kaputt_sperrt_statt_app_password(anonym, inhalt):
    """Kaputte Datei heißt nicht still wieder APP_PASSWORD: Das könnte das Passwort sein, das man loswerden wollte."""
    (config.DATA / 'passwort.json').write_text(inhalt)
    assert anmelden(anonym, ALT).status_code == 401
    assert 'beschädigt' in anonym.get('/login').text


def test_datei_unlesbar_sperrt(anonym):
    f = config.DATA / 'passwort.json'
    from app.main import SEC
    SEC.own.set(NEU)
    os.chmod(f, 0)
    try:
        if os.access(f, os.R_OK):
            pytest.skip('läuft als root')
        assert anmelden(anonym, ALT).status_code == 401 and anmelden(anonym, NEU).status_code == 401
    finally:
        os.chmod(f, 0o600)


def test_kaputte_datei_meldet_alle_ab(client):
    (config.DATA / 'passwort.json').write_text('{kaputt')
    assert client.get('/settings', follow_redirects=False).status_code == 303


def test_zurueck_belebt_alte_anmeldungen_nicht(client):
    """Browser angemeldet mit APP_PASSWORD, dann ändern und zurück: Das alte Cookie bleibt ungültig."""
    from app.main import SEC
    alt = dict(client.cookies)
    SEC.own.set(NEU)
    SEC.own.clear()
    client.cookies.clear()
    client.cookies.update(alt)
    assert client.get('/settings', follow_redirects=False).status_code == 303
    assert anmelden(client, ALT).status_code == 303  # APP_PASSWORD gilt aber wieder


def test_anderer_browser_verliert_tages_cookie(client):
    from app import security as sec, totp
    from app.main import SEC, app
    import time
    secret = SEC.totp.start()
    step = int(time.time() // totp.PERIOD)
    SEC.totp.activate(totp.code_at(secret, step))
    try:
        anderer = TestClient(app)
        anmelden(anderer, ALT)
        anderer.post('/login/code', data={'code': totp.code_at(secret, step + 1)})
        assert anderer.cookies.get(sec.DAY_COOKIE)
        SEC.own.set(NEU)
        r = anmelden(anderer, NEU)
        assert 'name="code"' in r.text  # Tages-Cookie gilt nicht mehr: wieder nach dem Code fragen
    finally:
        SEC.totp.disable()


def test_fremde_seite_kann_nicht_aendern(client):
    from app.main import SEC
    r = client.post('/settings/password', data={'current': ALT, 'new': NEU, 'repeat': NEU},
                    headers={'origin': 'http://boese.example'}, follow_redirects=False)
    assert 'err=' in r.headers['location'] and not SEC.own.active


def test_fehlversuche_beim_aendern_sperren_auch_die_anmeldung(client):
    from app import security as sec
    for _ in range(sec.MAX_FAILS):
        aendern(client, current='falsch')
    assert anmelden(client, ALT).status_code == 429


def test_befehl_gibt_root_ab(monkeypatch, tmp_path):
    """docker exec läuft als root, PermLens als 10001: erst auf den Besitzer des Daten-Ordners wechseln."""
    calls = []
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(os, 'stat', lambda p: type('S', (), {'st_uid': 10001, 'st_gid': 10002})())
    monkeypatch.setattr(os, 'setgroups', lambda g: calls.append(('groups', g)))
    monkeypatch.setattr(os, 'setgid', lambda g: calls.append(('gid', g)))
    monkeypatch.setattr(os, 'setuid', lambda u: calls.append(('uid', u)))
    passwort.drop_root(tmp_path)
    assert calls == [('groups', []), ('gid', 10002), ('uid', 10001)]


def test_befehl_schreibt_ins_protokoll(anonym):
    eingaben = iter([NEU, NEU])
    passwort.main([], ask=lambda _: next(eingaben))
    e = db.audit_entries(1)[0]
    assert e['action'] == 'passwort' and e['client'] == 'befehl'


def test_vorhandene_tmp_datei_wird_nicht_benutzt(tmp_path):
    ziel = tmp_path / 'ziel'
    ziel.write_text('bleibt')
    (tmp_path / 'passwort.tmp').symlink_to(ziel)
    passwort.Store(tmp_path).set(NEU)
    assert ziel.read_text() == 'bleibt'
    assert stat.S_IMODE(os.stat(tmp_path / 'passwort.json').st_mode) == 0o600
    assert not list(tmp_path.glob('.passwort-*'))


def test_ohne_app_password_reicht_eigenes(anonym, monkeypatch):
    from app.main import SEC
    monkeypatch.setattr(SEC, 'password', '')
    assert anonym.get('/login').status_code == 503
    SEC.own.set(NEU)
    assert anonym.get('/login').status_code == 200


def test_anmeldeseite_nennt_den_befehl(anonym):
    from app.main import SEC
    t = anonym.get('/login').text
    assert 'python -m app.passwort' in t and 'APP_PASSWORD' in t
    SEC.own.set(NEU)
    assert 'APP_PASSWORD' not in anonym.get('/login').text
