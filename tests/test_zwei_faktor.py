import os
import re
import time

import pytest

from app import db, security as sec, totp


@pytest.fixture(autouse=True)
def aus():
    from app.main import SEC
    SEC.totp.disable()
    yield
    SEC.totp.disable()


def jetzt(secret, delta=0):
    return totp.code_at(secret, int(time.time() // totp.PERIOD) + delta)


def einschalten(client):
    """Über die Einstellungen einrichten. Zurück: Schlüssel und Ersatz-Codes."""
    from app.main import SEC
    client.post('/settings/2fa/start')
    secret = SEC.totp.pending()
    r = client.post('/settings/2fa/confirm', data={'code': jetzt(secret)})
    assert r.status_code == 200 and SEC.totp.active
    return secret, ersatz_codes(r.text)


def ersatz_codes(html):
    return re.findall(r'\b[a-z2-9]{4}-[a-z2-9]{4}\b', html.split('id="tfa-codes">', 1)[1].split('</pre>', 1)[0])


# ---- Rechnung nach RFC 6238 (Testwerte aus Anhang B, SHA-1, 8 Stellen → hier die letzten 6)
def test_rfc6238():
    import base64
    secret = base64.b32encode(b'12345678901234567890').decode()
    assert totp.code_at(secret, 59 // 30) == '287082'
    assert totp.code_at(secret, 1111111109 // 30) == '081804'
    assert totp.code_at(secret, 2000000000 // 30) == '279037'


def test_abweichung_der_uhr():
    s = totp.new_secret()
    now = time.time()
    step = int(now // 30)
    assert totp.match(s, totp.code_at(s, step - 1), now) == step - 1
    assert totp.match(s, totp.code_at(s, step + 1), now) == step + 1
    assert totp.match(s, totp.code_at(s, step - 2), now) is None
    assert totp.match(s, 'abcdef', now) is None
    assert totp.match(s, totp.code_at(s, step)[:3] + ' ' + totp.code_at(s, step)[3:], now) == step


def test_qr_code():
    svg = totp.qr_svg(totp.uri('ABCDEF', '192.168.1.50'))
    assert svg.startswith('<svg') and 'pl-qr' in svg
    # Ohne feste Größe und mit viewBox, sonst schneidet das CSS den Code ab und keine App kann ihn lesen
    assert 'viewBox="0 0 ' in svg and 'width=' not in svg.split('>', 1)[0]
    assert totp.uri('ABC', 'x').startswith('otpauth://totp/PermLens:x?secret=ABC&issuer=PermLens')


# ---- Einrichten
def test_ohne_2fa_wie_bisher(anonym):
    r = anonym.post('/login', data={'password': os.environ['APP_PASSWORD'], 'next': '/'}, follow_redirects=False)
    assert r.status_code == 303


def test_einrichten_mit_falschem_code(client):
    from app.main import SEC
    client.post('/settings/2fa/start')
    r = client.get('/settings')
    assert 'otpauth' not in r.text and '<svg' in r.text and SEC.totp.pending() in r.text
    r = client.post('/settings/2fa/confirm', data={'code': '000000'}, follow_redirects=False)
    assert 'err=' in r.headers['location']
    assert not SEC.totp.active and SEC.totp.pending()  # noch nichts eingeschaltet, Einrichtung läuft weiter


def test_einrichten_abbrechen(client):
    from app.main import SEC
    client.post('/settings/2fa/start')
    client.post('/settings/2fa/cancel')
    assert not SEC.totp.pending() and not SEC.totp.file.exists()


def test_einschalten(client):
    secret, codes = einschalten(client)
    assert len(codes) == totp.RECOVERY_COUNT
    from app.main import SEC
    assert SEC.totp.file.stat().st_mode & 0o777 == 0o600
    assert client.get('/settings').status_code == 200  # dieser Browser bleibt angemeldet
    assert codes[0] not in client.get('/settings').text  # Ersatz-Codes nur einmal sichtbar
    assert any(e['action'] == 'zwei-faktor' and e['target'] == 'einschalten' for e in db.audit_entries(5))


def test_einschalten_meldet_andere_ab(client, anonym):
    from fastapi.testclient import TestClient
    from app.main import app
    anderer = TestClient(app)
    anderer.post('/login', data={'password': os.environ['APP_PASSWORD']})
    assert anderer.get('/', follow_redirects=False).status_code == 200
    einschalten(client)
    assert anderer.get('/', follow_redirects=False).status_code == 303


# ---- Anmelden mit 2FA
def anmelden(c):
    r = c.post('/login', data={'password': os.environ['APP_PASSWORD'], 'next': '/hosts'}, follow_redirects=False)
    assert r.status_code == 200 and 'Code aus der App' in r.text
    assert c.get('/', follow_redirects=False).status_code == 303  # Passwort allein reicht nicht
    return r


def test_anmelden_mit_code(client):
    from fastapi.testclient import TestClient
    from app.main import app
    secret, _ = einschalten(client)
    c = TestClient(app)
    anmelden(c)
    r = c.post('/login/code', data={'code': jetzt(secret, 1), 'next': '/hosts'}, follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/hosts'
    assert c.get('/', follow_redirects=False).status_code == 200
    assert db.audit_entries(1)[0]['result'] == 'ok'


def test_code_gilt_nur_einmal(client):
    from fastapi.testclient import TestClient
    from app.main import app
    secret, _ = einschalten(client)
    code = jetzt(secret, 1)
    c = TestClient(app)
    anmelden(c)
    assert c.post('/login/code', data={'code': code}, follow_redirects=False).status_code == 303
    c2 = TestClient(app)
    anmelden(c2)
    r = c2.post('/login/code', data={'code': code})
    assert r.status_code == 401 and 'schon benutzt' in r.text


def test_code_ohne_passwort(client):
    from fastapi.testclient import TestClient
    from app.main import app
    secret, _ = einschalten(client)
    c = TestClient(app)
    r = c.post('/login/code', data={'code': jetzt(secret)})
    assert r.status_code == 401 and 'abgelaufen' in r.text
    c.cookies.set(sec.STEP_COOKIE, c.cookies.get(sec.COOKIE) or '9999999999.abc')
    assert c.post('/login/code', data={'code': jetzt(secret)}).status_code == 401


def test_anmelde_cookie_ist_kein_zwischenschritt(client):
    """Das Cookie des Zwischenschritts darf nicht als Anmeldung gelten und umgekehrt."""
    from app.main import SEC
    einschalten(client)
    step = SEC.make_step_token()
    assert not SEC.token_ok(step)
    assert not SEC.step_ok(SEC.make_token())


def test_ersatz_code(client):
    from fastapi.testclient import TestClient
    from app.main import app, SEC
    _, codes = einschalten(client)
    c = TestClient(app)
    anmelden(c)
    assert c.post('/login/code', data={'code': codes[0].upper()}, follow_redirects=False).status_code == 303
    assert SEC.totp.recovery_left() == totp.RECOVERY_COUNT - 1
    c2 = TestClient(app)
    anmelden(c2)
    assert c2.post('/login/code', data={'code': codes[0]}).status_code == 401  # nur einmal
    assert any('"zweiter_faktor": "ersatz"' in (e['details'] or '') for e in db.audit_entries(5))


def test_sperre_beim_code(client):
    from fastapi.testclient import TestClient
    from app.main import app, SEC
    secret, _ = einschalten(client)
    SEC._fails.clear()
    c = TestClient(app)
    anmelden(c)
    for _ in range(sec.MAX_FAILS):
        c.post('/login/code', data={'code': '000000'})
    r = c.post('/login/code', data={'code': jetzt(secret)})
    assert r.status_code == 429 and 'Zu viele Fehlversuche' in r.text
    SEC._fails.clear()


# ---- Ändern und Ausschalten
def test_ausschalten_braucht_code(client):
    from app.main import SEC
    secret, _ = einschalten(client)
    r = client.post('/settings/2fa/off', data={'code': '000000'}, follow_redirects=False)
    assert 'err=' in r.headers['location'] and SEC.totp.active
    SEC._fails.clear()
    client.post('/settings/2fa/off', data={'code': jetzt(secret, 1)})
    assert not SEC.totp.active and not SEC.totp.file.exists()
    assert client.get('/', follow_redirects=False).status_code == 200  # bleibt angemeldet


def test_neue_ersatz_codes(client):
    from app.main import SEC
    secret, alt = einschalten(client)
    r = client.post('/settings/2fa/recovery', data={'code': jetzt(secret, 1)})
    neu = ersatz_codes(r.text)
    assert len(neu) == totp.RECOVERY_COUNT and not set(neu) & set(alt)
    assert SEC.totp.check(alt[0]) is None and SEC.totp.check(neu[0]) == 'ersatz'


def test_notausgang_datei_loeschen(client):
    from fastapi.testclient import TestClient
    from app.main import app, SEC
    einschalten(client)
    SEC.totp.file.unlink()
    c = TestClient(app)
    r = c.post('/login', data={'password': os.environ['APP_PASSWORD']}, follow_redirects=False)
    assert r.status_code == 303


# ---- Gültigkeit (ab 0.5.4): Passwort bis der Browser schließt, Code einmal am Tag
def test_anmeldung_endet_mit_dem_browser(anonym):
    r = anonym.post('/login', data={'password': os.environ['APP_PASSWORD']}, follow_redirects=False)
    cookie = r.headers['set-cookie'].lower()
    assert sec.COOKIE in cookie and 'max-age' not in cookie and 'expires' not in cookie


def code_eingeben(c, secret, delta=1):
    anmelden(c)
    return c.post('/login/code', data={'code': jetzt(secret, delta)}, follow_redirects=False)


def test_code_gilt_bis_mitternacht(client):
    from fastapi.testclient import TestClient
    from app.main import app, SEC
    secret, _ = einschalten(client)
    c = TestClient(app)
    r = code_eingeben(c, secret)
    tag = c.cookies.get(sec.DAY_COOKIE)
    assert tag and SEC.day_ok(tag)
    assert int(tag.split('.')[0]) == sec.end_of_day()
    assert int(c.cookies.get(sec.COOKIE).split('.')[0]) == sec.end_of_day()  # Anmeldung endet um 24:00
    assert 'max-age' in [h for h in r.headers.get_list('set-cookie') if sec.DAY_COOKIE in h][0].lower()
    # Browser geschlossen: Anmelde-Cookie weg, Tages-Cookie bleibt → nur das Passwort
    c.cookies.delete(sec.COOKIE)
    assert c.get('/', follow_redirects=False).status_code == 303
    r = c.post('/login', data={'password': os.environ['APP_PASSWORD'], 'next': '/'}, follow_redirects=False)
    assert r.status_code == 303 and c.get('/', follow_redirects=False).status_code == 200
    assert '"zweiter_faktor": "heute"' in db.audit_entries(1)[0]['details']


def test_tages_cookie_ersetzt_nicht_das_passwort(client):
    from fastapi.testclient import TestClient
    from app.main import app
    secret, _ = einschalten(client)
    c = TestClient(app)
    code_eingeben(c, secret)
    c.cookies.delete(sec.COOKIE)
    assert c.post('/login', data={'password': 'falsch'}).status_code == 401


def test_gefaelschtes_tages_cookie(client):
    from fastapi.testclient import TestClient
    from app.main import app, SEC
    einschalten(client)
    c = TestClient(app)
    c.cookies.set(sec.DAY_COOKIE, SEC.make_token())  # Anmelde-Cookie statt Tages-Cookie
    anmelden(c)
    c.cookies.set(sec.DAY_COOKIE, f'{sec.end_of_day()}.abc')
    anmelden(c)
    c.cookies.set(sec.DAY_COOKIE, SEC.make_token('tag', until=int(time.time()) - 1))  # gestern abgelaufen
    anmelden(c)


def test_abmelden_verlangt_wieder_den_code(client):
    from fastapi.testclient import TestClient
    from app.main import app
    secret, _ = einschalten(client)
    c = TestClient(app)
    code_eingeben(c, secret)
    c.get('/logout')
    assert not c.cookies.get(sec.DAY_COOKIE)
    anmelden(c)


def test_ohne_2fa_kein_tages_cookie_noetig(anonym):
    from app.main import SEC
    anonym.post('/login', data={'password': os.environ['APP_PASSWORD']})
    assert not anonym.cookies.get(sec.DAY_COOKIE)
    assert int(anonym.cookies.get(sec.COOKIE).split('.')[0]) > time.time() + sec.MAX_AGE - 60
    assert not SEC.totp.active


@pytest.fixture
def berlin():
    alt = os.environ.get('TZ')
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    yield
    if alt is None:
        os.environ.pop('TZ')
    else:
        os.environ['TZ'] = alt
    time.tzset()


def test_mitternacht_mit_sommerzeit(berlin):
    # 24.10.2026 mittags (Sommerzeit) → 25.10. 00:00; am 25.10. endet die Sommerzeit → 26.10. 00:00
    for tag, ziel in ((24, 25), (25, 26), (31, 1)):
        noon = time.mktime((2026, 10, tag, 12, 0, 0, 0, 0, -1))
        t = time.localtime(sec.end_of_day(noon))
        assert (t.tm_mday, t.tm_hour, t.tm_min) == (ziel, 0, 0)
    assert sec.end_of_day(time.mktime((2026, 10, 25, 12, 0, 0, 0, 0, -1))) - time.mktime(
        (2026, 10, 25, 0, 0, 0, 0, 0, -1)) == 25 * 3600  # der Tag hat 25 Stunden


def test_alte_anmeldungen_bis_0_5_3_gelten_nicht_mehr(anonym):
    """Bis 0.5.3 war die Signatur nur über die Ablaufzeit und das Cookie hielt 7 Tage über das Schließen hinaus."""
    import hashlib
    import hmac
    from app.main import SEC
    exp = int(time.time()) + 3600
    key = SEC.secret() + b'|' + hashlib.sha256(SEC.password.encode()).digest()
    alt = f'{exp}.' + hmac.new(key, str(exp).encode(), hashlib.sha256).hexdigest()
    anonym.cookies.set(sec.COOKIE, alt)
    assert anonym.get('/', follow_redirects=False).status_code == 303


def test_ersatz_codes_auf_eigener_seite(client):
    """Bis 0.5.4 standen die Codes in den Einstellungen und gingen unter, je nachdem wohin der Browser sprang."""
    from app.main import SEC
    client.post('/settings/2fa/start')
    r = client.post('/settings/2fa/confirm', data={'code': jetzt(SEC.totp.pending())})
    assert 'Ersatz-<em>Codes</em>' in r.text and 'Verbindung zum Proxmox' not in r.text
    assert len(ersatz_codes(r.text)) == totp.RECOVERY_COUNT
    assert r.headers['cache-control'] == 'no-store'
