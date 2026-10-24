"""App-Seite von Wächter-Script Version 3: lxc.mount.entry auf dem Host, /etc/exports, Gegenprobe."""
from concurrent.futures import ThreadPoolExecutor

from app import db
from app.pve import findings, parse, scan, ssh, view
from conftest import set_pve  # noqa: E402

DIR = {'mode': 'drwxrwxrwx', 'octal': '777', 'uid': 65534, 'gid': 65534, 'user': '', 'group': '', 'type': 'directory'}


def test_exports():
    e = parse.exports('# Kommentar\n/srv/daten 192.168.1.0/24(rw,all_squash,anonuid=1000,anongid=1000) mac(ro)\n'
                      '"/srv/mit leer" *(rw,no_root_squash)\n')
    assert e[0]['path'] == '/srv/daten' and e[0]['clients'][0]['options']['anonuid'] == '1000'
    assert e[0]['clients'][1] == {'host': 'mac', 'options': {'ro': True}}
    assert e[1]['path'] == '/srv/mit leer' and e[1]['clients'][0]['options']['no_root_squash']


def test_mount_entry_mit_waechter3_wird_auf_dem_host_gelesen(monkeypatch):
    guests = [{'vmid': 1, 'config': {'mounts': [{'key': 'lxc.mount.entry', 'source': '/mnt/nas', 'target': '/mnt/nas',
                                                  'kind': 'bind', 'entry': True}]}}]
    calls = []

    def run(h, a, p=22, timeout=75):
        calls.append(a)
        if a[0] == 'stat':
            return ssh.Result(0, 'drwxr-xr-x|755|0|0|root|root|directory|/mnt/nas\n', '')
        return ssh.Result(0, '{"path": "/mnt/nas", "access": [], "default": []}', '')
    monkeypatch.setattr(ssh, 'run', run)
    with ThreadPoolExecutor(2) as pool:
        scan._mount_info('h', 22, guests, [], pool, guard=3)
    m = guests[0]['config']['mounts'][0]
    assert m['host_stat']['uid'] == 0 and not m.get('host_unchecked')
    assert ['stat', '-c', scan.STAT[2], '/mnt/nas'] in calls


def test_exports_nur_mit_waechter3(monkeypatch):
    calls = []
    monkeypatch.setattr(ssh, 'run', lambda h, a, p=22, timeout=75: calls.append(a) or ssh.Result(0, '/srv *(rw,no_root_squash)\n', ''))
    guest = {'vmid': 7, 'config': {'mounts': []}}
    assert scan._details('h', 22, guest, guard=2)['exports'] == []
    assert not any(a[-2:] == ['cat', '/etc/exports'] for a in calls)
    d = scan._details('h', 22, guest, guard=3)
    assert d['exports'][0]['path'] == '/srv'
    g = {'vmid': 7, 'name': 'nfs', 'type': 'lxc', 'status': 'running', 'config': {'unprivileged': True, 'mounts': []},
         'details': {'users': [], 'groups': [], 'stat': {}, 'exports': d['exports']}}
    assert any(f['key'] == 'no_root_squash' for f in findings.collect({'host_info': {}, 'guests': [g]}))


def test_gegenprobe_befehle(monkeypatch):
    calls = []

    def run(h, a, p=22, timeout=75):
        calls.append(a)
        return ssh.Result(1 if a[-2] == '-w' else 0, '', '')
    monkeypatch.setattr(ssh, 'run', run)
    r = scan.probe('h', 22, 9004, 1000, 1000, [2000], '/mnt/test')
    assert r == {'error': '', 'r': True, 'w': False, 'x': True}
    assert calls[0] == ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--groups=1000,2000',
                        '--', 'test', '-r', '/mnt/test']
    calls.clear()
    scan.probe('h', 22, 9004, 1000, 1000, [], '/mnt/test')
    assert calls[0][7] == '--clear-groups'


def test_gegenprobe_alter_waechter(monkeypatch):
    monkeypatch.setattr(ssh, 'run', lambda h, a, p=22, timeout=75: ssh.Result(ssh.DENIED, '', ''))
    assert 'Neu einrichten' in scan.probe('h', 22, 1, 1000, 1000, [], '/x')['error']


def _nfs_scan(monkeypatch):
    g = {'vmid': 9004, 'name': 'ppm-test-nfs', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': True, 'idmap': [], 'mounts': [
             {'key': 'mp0', 'source': '/mnt/nfs', 'target': '/mnt/test', 'kind': 'bind', 'fs_kind': 'nfs', 'host_stat': DIR}]},
         'details': {'users': [{'name': 'alice', 'uid': 1000, 'gid': 1000}], 'groups': [],
                     'stat': {'/': {**DIR, 'uid': 0, 'gid': 0, 'octal': '755'}, '/mnt': {**DIR, 'uid': 0, 'gid': 0, 'octal': '755'},
                              '/mnt/test': DIR}}}
    s = {'host': '10.0.0.5', 'finished': '2026-10-19T10:00:00+00:00', 'host_info': {}, 'guests': [g]}
    monkeypatch.setattr(scan, 'latest', lambda i=None: s)
    set_pve(pve_host='10.0.0.5', pve_port='22', pve_connected='1')


def test_diagnose_gegenprobe_weicht_ab(client, monkeypatch):
    _nfs_scan(monkeypatch)
    set_pve(pve_guard='3')
    r = client.get('/diagnose?ct=9004&uid=1000&path=/mnt/test')
    assert 'Gegenprobe: das System selbst fragen' in r.text
    # UGREEN: rwxrwxrwx, lehnt Schreiben trotzdem ab
    monkeypatch.setattr(ssh, 'run', lambda h, a, p=22, timeout=75: ssh.Result(1 if a[-2] == '-w' else 0, '', ''))
    r = client.get('/diagnose?ct=9004&uid=1000&path=/mnt/test&probe=1')
    assert "Lesen ja, Schreiben nein" in r.text and "weicht von der Rechnung ab" in r.text and "nur ein Hinweis" in r.text
    assert db.audit_entries(1)[0]['action'] == 'gegenprobe'


def test_diagnose_ohne_waechter3_kein_knopf(client, monkeypatch):
    _nfs_scan(monkeypatch)
    set_pve(pve_guard='2')
    r = client.get('/diagnose?ct=9004&uid=1000&path=/mnt/test&probe=1')
    assert 'Gegenprobe: das System selbst fragen' not in r.text and 'Wächter-Script Version 3' in r.text
