import os

from app import db, security as sec


def test_ohne_anmeldung_zur_anmeldeseite(anonym):
    r = anonym.get('/?x=1', follow_redirects=False)
    assert r.status_code == 303
    assert r.headers['location'] == '/login?next=/%3Fx%3D1'


def test_offene_seiten_ohne_anmeldung(anonym):
    assert anonym.get('/healthz').status_code == 200
    assert anonym.get('/static/style.css').status_code == 200
    assert anonym.get('/login').status_code == 200


def test_richtiges_passwort(anonym):
    r = anonym.post('/login', data={'password': os.environ['APP_PASSWORD'], 'next': '/'}, follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/'
    assert 'httponly' in r.headers['set-cookie'].lower()
    assert anonym.get('/').status_code == 200
    assert any(e['action'] == 'login' and e['result'] == 'ok' for e in db.audit_entries(5))


def test_falsches_passwort(anonym):
    r = anonym.post('/login', data={'password': 'falsch', 'next': '/'})
    assert r.status_code == 401
    assert 'Falsches Passwort.' in r.text
    assert anonym.get('/', follow_redirects=False).status_code == 303
    assert db.audit_entries(1)[0]['result'] == 'fehler'


def test_sperre_nach_fehlversuchen(anonym):
    for _ in range(sec.MAX_FAILS):
        anonym.post('/login', data={'password': 'falsch'})
    r = anonym.post('/login', data={'password': os.environ['APP_PASSWORD']}, follow_redirects=False)
    assert r.status_code == 429  # auch das richtige Passwort hilft während der Sperre nicht
    assert 'Zu viele Fehlversuche' in r.text


def test_weiterleitung_nur_intern(anonym):
    r = anonym.post('/login', data={'password': os.environ['APP_PASSWORD'], 'next': 'https://boese.example'},
                    follow_redirects=False)
    assert r.headers['location'] == '/'


def test_abmelden(client):
    client.get('/logout')
    assert client.get('/', follow_redirects=False).status_code == 303


def test_gefaelschtes_cookie(anonym):
    anonym.cookies.set(sec.COOKIE, '9999999999.abc')
    assert anonym.get('/', follow_redirects=False).status_code == 303


def test_ohne_passwort_nur_hinweis(anonym, monkeypatch):
    from app.main import SEC
    monkeypatch.setattr(SEC, 'password', 'kurz')
    r = anonym.get('/login')
    assert r.status_code == 503
    assert 'Kein Passwort gesetzt' in r.text
    assert anonym.get('/healthz').status_code == 200


def test_heimnetz():
    assert sec.is_local('192.168.1.10')
    assert sec.is_local('100.64.1.2')  # Tailscale
    assert sec.is_local('::1')
    assert not sec.is_local('8.8.8.8')
