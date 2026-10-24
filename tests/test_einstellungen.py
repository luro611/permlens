from app import db
from app.pve import ssh
from conftest import get_pve, set_pve  # noqa: E402


def test_seite_braucht_anmeldung(anonym):
    assert anonym.get('/settings', follow_redirects=False).status_code == 303


def test_waechter_download_ohne_anmeldung(anonym):
    r = anonym.get('/host/permlens-guard')
    assert r.status_code == 200
    assert r.text.startswith('#!/usr/bin/env python3')


def test_speichern_und_ungueltige_adresse(client):
    r = client.post('/settings/pve', data={'host': '192.168.1.10', 'port': '22', 'lxc_ip': '192.168.1.60'})
    assert 'Gespeichert.' in r.text
    assert get_pve('pve_host') == '192.168.1.10'
    r = client.post('/settings/pve', data={'host': '-oProxyCommand=boese', 'port': '22', 'lxc_ip': ''})
    assert 'ungültig' in r.text
    assert get_pve('pve_host') == '192.168.1.10'
    r = client.post('/settings/pve', data={'host': '192.168.1.10', 'port': '99999', 'lxc_ip': ''})
    assert 'Der SSH-Port ist ungültig.' in r.text


def test_schluessel_und_zeile(client):
    client.post('/settings/pve', data={'host': '192.168.1.10', 'port': '22', 'lxc_ip': '192.168.1.60'})
    r = client.post('/settings/key')
    assert ssh.has_key()
    assert (ssh.DIR.stat().st_mode & 0o777) == 0o700
    line = ssh.authorized_line('192.168.1.60')
    assert line.startswith('command="/usr/local/sbin/permlens-guard",restrict,from="192.168.1.60" ssh-ed25519 ')
    assert line in r.text.replace('&#34;', '"') or 'Schritt B' in r.text
    assert db.audit_entries(1)[0]['action'] == 'schluessel'


def test_ohne_schluessel_kein_befehl(monkeypatch):
    monkeypatch.setattr(ssh, 'KEY', ssh.DIR / 'gibt-es-nicht')
    r = ssh.run('192.168.1.10', ['pct', 'list'])
    assert r.rc == 255 and 'Schlüssel' in r.err


def test_verstaendliche_fehler():
    assert 'kennt den Schlüssel' in ssh.explain(ssh.Result(255, '', 'root@x: Permission denied (publickey).'))
    assert 'abgelehnt' in ssh.explain(ssh.Result(126, '', ''))
    assert 'antwortet nicht' in ssh.explain(ssh.Result(255, '', 'ssh: connect to host x port 22: Operation timed out'))


def test_eigene_adresse_wird_erkannt(client):
    set_pve(lxc_ip='')
    r = client.get('/settings', headers={'host': '192.168.1.50'})
    assert 'value="192.168.1.50"' in r.text
    assert 'automatisch erkannt' in r.text
    assert db.get_setting('lxc_ip') == '192.168.1.50'
    r = client.get('/settings', headers={'host': '192.168.1.50'})
    assert 'automatisch erkannt' not in r.text  # nur beim ersten Mal


def test_keine_erkennung_bei_namen_oder_localhost(client):
    for host in ('permlens.example', '127.0.0.1:8000'):
        set_pve(lxc_ip='')
        client.get('/settings', headers={'host': host})
        assert db.get_setting('lxc_ip') == ''


def test_erster_erfolgreicher_test_liest_ein(client, monkeypatch):
    from app.pve import scan
    set_pve(pve_host='10.0.0.7', pve_port='22')
    ok = [{'name': 'x', 'ok': True, 'detail': ''}]
    monkeypatch.setattr(ssh, 'test_connection', lambda h, p: ok)
    called = []
    monkeypatch.setattr(scan, 'run', lambda h, p, i=None: called.append(h) or {'error': '', 'guests': []})
    monkeypatch.setattr(scan, 'latest', lambda i=None: None)
    r = client.post('/settings/test', follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/'
    assert called == ['10.0.0.7']
    monkeypatch.setattr(scan, 'latest', lambda i=None: {'host': '10.0.0.7', 'finished': '2026-10-19T15:46:00+00:00'})
    warten_bis_fertig(scan)
    r = client.post('/settings/test', follow_redirects=False)
    warten_bis_fertig(scan)
    # auch danach wird neu eingelesen, sonst bliebe der alte Stand stehen; die Seite bleibt aber stehen
    assert r.status_code == 200 and called == ['10.0.0.7', '10.0.0.7']
    assert 'Es liest jetzt neu ein' in r.text and 'Zuletzt eingelesen:' in r.text


def warten_bis_fertig(scan):
    import time
    for _ in range(100):
        if not scan.running():
            return
        time.sleep(0.01)


def test_waechter_version_wird_angezeigt(client, monkeypatch):
    from app import main
    from app.pve import scan
    set_pve(pve_host='10.0.0.7', pve_port='22', pve_connected='1', pve_guard='')
    r = client.get('/settings')
    assert 'Wächter-Script:' in r.text and 'unbekannt' in r.text
    ok = [{'name': 'x', 'ok': True, 'detail': '', 'guard': '1'}]
    monkeypatch.setattr(ssh, 'test_connection', lambda h, p: ok)
    monkeypatch.setattr(scan, 'latest', lambda i=None: {'host': '10.0.0.7'})
    monkeypatch.setattr(scan, 'run', lambda h, p, i=None: {'error': '', 'guests': []})
    client.post('/settings/test')
    warten_bis_fertig(scan)
    assert get_pve('pve_guard') == '1'
    r = client.get('/settings')
    assert 'Version 1' in r.text and 'ältere Version' in r.text  # mitgeliefert ist eine neuere
    set_pve(pve_guard=main.guard_version())
    r = client.get('/settings')
    assert f'Version {main.guard_version()}' in r.text and 'ältere Version' not in r.text
