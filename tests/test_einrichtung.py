"""Einrichtung mit einem Befehl: Einmal-Code, Script für den Proxmox, Rückmeldung."""
import hashlib
import html
import re
import subprocess

from app import db, setup
from app.pve import ssh
from conftest import get_pve, set_pve  # noqa: E402

HOSTKEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEbeispielEbeispielEbeispielEbeispiel12'


def fresh():
    set_pve(pve_host='', pve_port='22', pve_connected='0', lxc_ip='', pve_node='')
    return setup.renew()


def test_code_gilt_nur_kurz_und_einmal(monkeypatch):
    tok = fresh()
    assert setup.check(tok) and setup.token() == tok
    assert not setup.check('0' * 32) and not setup.check('../etc') and not setup.check('')
    setup.used()
    assert not setup.check(tok)
    tok = setup.token()
    import time
    monkeypatch.setattr(time, 'time', lambda: 10 ** 12)
    assert not setup.check(tok)


def test_startseite_zeigt_befehl(client):
    tok = fresh()
    r = client.get('/')
    assert 'Ein Befehl auf dem Proxmox' in r.text
    assert f'curl -fsSL http://testserver/setup/{tok} -o' in r.text and '| bash' not in r.text
    assert ssh.has_key()  # Schlüssel wird automatisch erzeugt


def test_befehl_prueft_pruefsumme(anonym, client):
    """Die Prüfsumme im Befehl passt genau zum ausgelieferten Script, und der Befehl ist gültiges Bash."""
    tok = fresh()
    cmd = html.unescape(re.search(r'<pre id="cmd-setup">(.*?)</pre>', client.get('/').text, re.S).group(1))
    sha = re.search(r'echo "([0-9a-f]{64})  \$f" \| sha256sum -c --status', cmd).group(1)
    assert hashlib.sha256(anonym.get(f'/setup/{tok}').content).hexdigest() == sha
    assert 'then bash "$f"' in cmd and 'nichts ausgeführt' in cmd
    assert subprocess.run(['bash', '-n'], input=cmd, text=True).returncode == 0


def test_ungueltige_adresse(anonym):
    tok = fresh()
    for bad in ('x";id;"', 'a$(id)', 'host name', 'a`id`'):
        assert not setup.valid_origin(f'http://{bad}')
        assert 'echo "PermLens: Ungültige Adresse' in setup.command(f'http://{bad}', tok, '0' * 64)
    for good in ('http://192.168.1.50:8000', 'http://permlens', 'https://permlens.lan', 'http://[fd00::51]:8000'):
        assert setup.valid_origin(good)
    r = anonym.get(f'/setup/{tok}', headers={'host': 'a$(id)'})
    assert 'exit 1' in r.text and '$(id)' not in r.text


def test_script(anonym, client):
    tok = fresh()
    client.get('/')
    r = anonym.get(f'/setup/{tok}')  # ohne Anmeldung, der Proxmox hat kein Cookie
    assert r.status_code == 200
    s = r.text
    assert s.startswith('#!/bin/bash') and tok in s and ssh.public_key() in s
    assert 'sha256sum -c' in s and 'permlens-guard' in s
    assert 'restrict,from=' in s
    assert subprocess.run(['bash', '-n'], input=s, text=True).returncode == 0  # Syntax ok
    bad = anonym.get('/setup/' + '0' * 32)
    assert 'abgelaufen oder schon benutzt' in bad.text and 'exit 1' in bad.text


def test_rueckmeldung(anonym, client, monkeypatch):
    tok = fresh()
    client.get('/')
    ok = [{'name': 'Verbindung und Wächter-Script', 'ok': True, 'detail': ''}]
    monkeypatch.setattr(ssh, 'test_connection', lambda h, p: ok)
    from app.pve import scan
    monkeypatch.setattr(scan, 'run', lambda h, p, i=None: {'error': '', 'guests': []})
    monkeypatch.setattr(scan, 'latest', lambda i=None: None)
    data = {'host': '10.0.0.5', 'port': '22', 'node': 'pve-test', 'lxc_ip': '10.0.0.51', 'hostkey': HOSTKEY}
    r = anonym.post(f'/setup/{tok}/fertig', data=data)
    assert r.status_code == 200 and 'Fertig' in r.text
    assert get_pve('pve_host') == '10.0.0.5' and get_pve('pve_node') == 'pve-test'
    assert db.get_setting('lxc_ip') == '10.0.0.51' and get_pve('pve_connected') == '1'
    assert ssh.KNOWN.read_text() == f'10.0.0.5 {HOSTKEY}\n'
    assert anonym.get('/setup/status').json() == {'connected': True}
    # zweimal geht nicht
    assert anonym.post(f'/setup/{tok}/fertig', data=data).status_code == 403
    # verbunden: Startseite zeigt keinen Befehl mehr
    assert 'Ein Befehl auf dem Proxmox' not in client.get('/').text


def test_rueckmeldung_mit_falschen_werten(anonym):
    tok = fresh()
    for bad in ({'host': '-oProxyCommand=x'}, {'port': '0'}, {'hostkey': 'kaputt'}, {'lxc_ip': 'a b'}):
        data = {'host': '10.0.0.5', 'port': '22', 'node': 'x', 'lxc_ip': '10.0.0.51', 'hostkey': HOSTKEY, **bad}
        r = anonym.post(f'/setup/{tok}/fertig', data=data)
        assert r.status_code == 400, bad
    assert get_pve('pve_host') == ''


def test_neu_einrichten(client):
    set_pve(pve_host='10.0.0.5', pve_connected='1')
    r = client.get('/settings')
    assert 'Verbunden' in r.text and 'Ein Befehl auf dem Proxmox' not in r.text
    r = client.post('/settings/setup-new')
    assert 'Ein Befehl auf dem Proxmox' in r.text
    # Die Seite darf nicht gleich weiterspringen: verbunden erst, wenn der neue Befehl gelaufen ist
    assert client.get('/setup/status').json() == {'connected': False}
    setup.used()
    assert client.get('/setup/status').json() == {'connected': True}
