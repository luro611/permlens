"""Mehrere Proxmox (0.5.0): Übernahme der alten Verbindung, weiterer Host per Einrichtung, Umschalten,
eingelesener Stand je Host und Schutz davor, eine Vorschau auf dem falschen Proxmox auszuführen."""
from contextlib import closing

import pytest

from app import db, main, setup
from app.pve import scan, ssh
from test_aenderungen import GUEST, Proxmox

HOSTKEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB0p6Vb1ZbVb0mGQmXw6Wd3c0A5pX7XqzQ3q8eXl8dK2'
HOSTKEY2 = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC9yYq2kq9u8E1oPq3Y7Zl2m0Wn4b5c6d7e8f9a0b1c2d3e4'


def leeren():
    with closing(db.connect()) as c, c:
        c.execute('DELETE FROM scans')
        c.execute('DELETE FROM hosts')
        c.execute("DELETE FROM settings WHERE key LIKE 'pve_%' OR key = 'setup_last_host'")


@pytest.fixture
def zwei(client, monkeypatch):
    """Zwei Proxmox: A (nur lesen) und B (schreiben in 9003), jeder mit eigenem Stand."""
    leeren()
    a = db.add_host('10.0.0.5', 22, name='pve-haus', connected=1, guard='7')
    b = db.add_host('10.0.0.8', 22, name='pve10', connected=1, guard='7', write_ids='9003')
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.5', 'host_id': a, 'error': '',
               'guests': [{**GUEST, 'name': 'auf-a'}]})
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'host_id': b, 'error': '',
               'guests': [{**GUEST, 'name': 'auf-b'}]})
    p = Proxmox()
    calls = []
    monkeypatch.setattr(ssh, 'run', lambda host, *a_, **k: calls.append(host) or p(host, *a_, **k))
    monkeypatch.setattr(scan, 'start', lambda *a_, **k: True)
    return a, b, calls


def waehlen(client, hid):
    r = client.post(f'/hosts/{hid}/waehlen', follow_redirects=False)
    assert r.status_code == 303
    return r


def test_uebernahme_der_alten_verbindung():
    leeren()
    db.set_settings(pve_host='192.168.1.10', pve_port='22', pve_node='pve-haus', lxc_ip='192.168.1.50',
                    pve_guard='7', pve_write='151', pve_connected='1')
    with closing(db.connect()) as c, c:
        c.execute("INSERT INTO scans (started, finished, result) VALUES ('', 'x', '{\"host\": \"192.168.1.10\"}')")
    hid = db.migrate_host()
    h = db.host(hid)
    assert (h['name'], h['host'], h['node'], h['lxc_ip'], h['guard'], h['write_ids'], h['connected']) == \
        ('pve-haus', '192.168.1.10', 'pve-haus', '192.168.1.50', '7', '151', 1)
    assert scan.latest(hid) == {'host': '192.168.1.10'}  # alter Stand gehört jetzt zu diesem Host
    assert db.get_setting('pve_host') == '' and db.migrate_host() is None  # nur einmal


def test_stand_je_host_und_umschalten(client, zwei):
    a, b, _ = zwei
    assert 'auf-a' in client.get('/').text  # ohne Wahl: der erste Host
    waehlen(client, b)
    r = client.get('/')
    assert 'auf-b' in r.text and 'auf-a' not in r.text
    assert 'pl-hostbar' in r.text and 'pve10' in r.text  # Umschalter mit dem Namen
    waehlen(client, a)
    assert 'auf-a' in client.get('/').text


def test_umschalten_nur_bekannte_hosts(client, zwei):
    r = client.post('/hosts/999/waehlen', follow_redirects=False)
    assert 'permlens_host' not in r.headers.get('set-cookie', '')


def test_vorschau_gilt_nur_fuer_ihren_proxmox(client, zwei):
    a, b, calls = zwei
    waehlen(client, b)
    form = {'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'projekt', 'gid': '2001'}
    r = client.post('/aenderung/vorschau', data=form)
    assert f'name="host_id" value="{b}"' in r.text and 'Proxmox pve10' in r.text
    waehlen(client, a)  # z. B. in einem anderen Tab umgeschaltet
    calls.clear()
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': str(b)}, follow_redirects=False)
    assert r.status_code == 200 and 'gehört zu einem anderen Proxmox' in r.text
    assert not any(c for c in calls)  # nichts ausgeführt, auf keinem Host


def test_aenderung_laeuft_auf_dem_gewaehlten_host(client, zwei):
    a, b, calls = zwei
    waehlen(client, b)
    form = {'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'projekt', 'gid': '2001', 'host_id': str(b)}
    calls.clear()
    r = client.post('/aenderung/ausfuehren', data=form, follow_redirects=False)
    assert r.status_code == 303 and calls and set(calls) == {'10.0.0.8'}
    assert 'groupadd -g 2001 projekt' in client.get('/aenderungen').text
    waehlen(client, a)
    r = client.get('/aenderungen')
    assert 'groupadd -g 2001 projekt' not in r.text and 'Die der anderen Proxmox' in r.text
    cid = next(e['id'] for e in __import__('app.pve.change', fromlist=['x']).entries() if e['host'] == '10.0.0.8')
    r = client.post(f'/aenderungen/{cid}/rueckgaengig', follow_redirects=False)
    assert r.status_code == 303  # Rückgängig nur, wenn dieser Proxmox gewählt ist


def test_weiterer_proxmox_per_einrichtung(anonym, client, zwei, monkeypatch):
    a, b, _ = zwei
    ssh.KNOWN.parent.mkdir(parents=True, exist_ok=True)
    ssh.KNOWN.write_text(f'10.0.0.5 {HOSTKEY}\n')
    tok = setup.renew()
    monkeypatch.setattr(ssh, 'test_connection', lambda h, p: [{'name': 'x', 'ok': True, 'detail': '', 'guard': '7'}])
    data = {'host': '10.0.0.9', 'port': '22', 'node': 'arbeit', 'lxc_ip': '10.0.0.51', 'hostkey': HOSTKEY2}
    assert 'Fertig' in anonym.post(f'/setup/{tok}/fertig', data=data).text
    hosts = db.hosts()
    assert [h['host'] for h in hosts] == ['10.0.0.5', '10.0.0.8', '10.0.0.9']
    new = hosts[-1]
    assert new['name'] == 'arbeit' and new['connected'] == 1
    assert ssh.KNOWN.read_text() == f'10.0.0.5 {HOSTKEY}\n10.0.0.9 {HOSTKEY2}\n'  # alter Schlüssel bleibt
    r = client.get('/setup/status')
    assert r.json() == {'connected': True} and f'permlens_host={new["id"]}' in r.headers['set-cookie']


def test_umbenennen_und_entfernen(client, zwei):
    a, b, _ = zwei
    ssh.KNOWN.write_text(f'10.0.0.5 {HOSTKEY}\n10.0.0.8 {HOSTKEY2}\n')
    client.post(f'/hosts/{b}/umbenennen', data={'name': '  Test   Server '})
    assert db.host(b)['name'] == 'Test Server'
    waehlen(client, b)
    r = client.post(f'/hosts/{b}/entfernen', follow_redirects=False)
    assert r.status_code == 303 and 'permlens_host=' in r.headers['set-cookie']  # Wahl zurückgesetzt
    assert db.host(b) is None and scan.latest(b) is None and scan.latest(a) is not None
    assert ssh.KNOWN.read_text() == f'10.0.0.5 {HOSTKEY}\n'


def test_fremde_seite_kann_nicht_umschalten(client, zwei):
    a, b, _ = zwei
    r = client.post(f'/hosts/{b}/waehlen', headers={'origin': 'https://boese.example'}, follow_redirects=False)
    assert 'permlens_host' not in r.headers.get('set-cookie', '')
    r = client.post(f'/hosts/{b}/entfernen', headers={'origin': 'https://boese.example'}, follow_redirects=False)
    assert db.host(b) is not None


def test_einstellungen_zeigen_alle_hosts(client, zwei):
    r = client.get('/settings')
    assert 'id="proxmox"' in r.text and 'pve-haus' in r.text and 'pve10' in r.text
    assert 'Weiteren Proxmox hinzufügen' in r.text and 'Container 9003' in r.text


def test_main_hat_keine_alten_verbindungsdaten():
    assert 'pve_host' not in open(main.__file__, encoding='utf-8').read()
