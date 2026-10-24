import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_healthz(anonym):
    client = anonym
    r = client.get('/healthz')
    assert r.status_code == 200
    assert r.json()['ok'] is True


def test_startseite_deutsch(client):
    r = client.get('/')
    assert r.status_code == 200
    assert 'Perm<em>Lens</em>' in r.text
    assert 'Übersicht' in r.text
    assert 'Kein offizielles Proxmox-Projekt' in r.text


def test_sprachwechsel_englisch(client):
    r = client.get('/lang/en?next=/', follow_redirects=False)
    assert r.status_code == 303
    assert r.cookies.get('permlens_lang') == 'en'
    client.cookies.set('permlens_lang', 'en')
    r = client.get('/')
    assert 'Overview' in r.text
    assert 'Not an official Proxmox project' in r.text


def test_sprachwechsel_nur_interne_ziele(anonym):
    client = anonym
    r = client.get('/lang/de?next=//boese.example', follow_redirects=False)
    assert r.headers['location'] == '/'


def test_stil_und_schriften_vorhanden(anonym):
    client = anonym
    for f in ('style.css', 'permlens.css'):
        assert client.get(f'/static/{f}').status_code == 200
    for font in re.findall(r"url\('fonts/([^']+)'\)", (ROOT / 'static' / 'style.css').read_text()):
        assert (ROOT / 'static' / 'fonts' / font).exists(), font


def test_alle_vorlagentexte_uebersetzt():
    """Jeder Text in _("…") der Vorlagen hat eine englische Übersetzung."""
    en = json.loads((ROOT / 'app' / 'locales' / 'en.json').read_text(encoding='utf-8'))
    fehlt = set()
    for t in (ROOT / 'app' / 'templates').glob('*.html'):
        for key in re.findall(r'''_\((?:"([^"]+)"|'([^']+)')''', t.read_text(encoding='utf-8')):
            k = ' '.join((key[0] or key[1]).split())
            if k not in en:
                fehlt.add(k)
    assert not fehlt, fehlt


def test_diagnose_texte_uebersetzt():
    """Texte aus dem Rechte-Rechner und die Ursachen der Diagnose-Seite haben eine englische Übersetzung."""
    from app import main
    en = json.loads((ROOT / 'app' / 'locales' / 'en.json').read_text(encoding='utf-8'))
    texts = set(main.CAUSES.values())
    for f in ('access.py', 'view.py', 'findings.py', 'scan.py', 'change.py', 'bauplan.py', 'explain.py'):
        src = (ROOT / 'app' / 'pve' / f).read_text(encoding='utf-8')
        # Texte in Tupeln und in advice(…), auch über mehrere Zeilen; keine Funktionsaufrufe wie .get('read only')
        for m in re.finditer(r"(?:(?<![\w.])|(?<=advice))\(((?:\s*'[^']*'\s*)+)[,)]", src):
            t = ''.join(re.findall(r"'([^']*)'", m.group(1)))
            if ' ' in t:  # Sätze, keine Schlüssel wie 'access'
                texts.add(t)
    from app.pve import explain  # Wörterbücher mit Klartext (0.5.1)
    texts |= set(explain.SYSTEM.values()) | set(explain.PERM.values()) | set(explain.CONF.values())
    assert 'root darf alles' in texts and 'Besitzer (§): §' in texts
    assert any(t.startswith('Mapping einrichten:') for t in texts)
    assert not [t for t in texts if t not in en]


def test_alte_adressen_leiten_weiter(client):
    """Usability 0.4.1: Speicher, Host und Benutzer stehen jetzt unter „Ordner“."""
    for old, new in (('/speicher', '/ordner'), ('/host', '/ordner/host'), ('/benutzer', '/ordner/nummern')):
        r = client.get(old, follow_redirects=False)
        assert r.status_code == 301 and r.headers['location'] == new


def test_menue_mit_fuenf_punkten(client):
    r = client.get('/ordner')
    for href in ('href="/probleme"', 'href="/diagnose"', 'href="/ordner"', 'href="/mapping"', 'href="/aenderungen"',
                 'href="/settings"', 'href="/logout"'):
        assert href in r.text, href
    assert 'href="/speicher"' not in r.text and 'href="/benutzer"' not in r.text


def test_leere_und_ungueltige_werte_in_der_adresse(client):
    """Rückmeldung Lutz (0.5.2): „Anleitung zeigen“ ohne Auswahl zeigte eine rohe Fehlermeldung (ct=)."""
    for url in ('/mapping?art=umstieg&ct=', '/mapping?art=bestehend&ct=', '/diagnose?ct=&uid=&path=',
                '/diagnose?ct=9001&uid=&path=&probe=', '/aenderungen?neu='):
        r = client.get(url)
        assert r.status_code == 200 and 'int_parsing' not in r.text, url
    for url in ('/mapping?art=umstieg&ct=abc', '/container/abc', '/aenderungen?neu=x'):
        r = client.get(url)
        assert r.status_code == 400 and 'Ungültige' in r.text and 'int_parsing' not in r.text, url
