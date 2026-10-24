"""Rechte-Rechner (AP 2.1) mit den Fällen aus der Testumgebung (Test-Container 9001 bis 9005)."""
from pathlib import Path

from app.pve import access, parse, view

ROOT_DIR = {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 0, 'gid': 0, 'type': 'directory'}
ALICE = {'uid': 1000, 'gid': 1000, 'gids': []}
BOB = {'uid': 1001, 'gid': 1001, 'gids': []}
ROOT = {'uid': 0, 'gid': 0, 'gids': []}


def d(uid, gid, octal, mode=''):
    return {'mode': mode or 'd?????????', 'octal': octal, 'uid': uid, 'gid': gid, 'type': 'directory'}


def chain(target_stat, acl=None):
    return [{'path': '/', 'stat': ROOT_DIR}, {'path': '/mnt', 'stat': ROOT_DIR},
            {'path': '/mnt/share', 'stat': target_stat, 'acl': acl}]


SHARE = d(1000, 1000, '2775')        # so sieht ihn ein privilegierter Container oder 9005 (1000 durchgereicht)
SHARE_NOBODY = d(65534, 65534, '2775')  # so sieht ihn 9002 (Standard-Mapping)


def test_9001_privilegiert_alice_darf_schreiben():
    r = access.check(ALICE, chain(SHARE))
    assert r['read'] and r['write'] and r['cause'] == ''
    assert r['steps'][-1]['why'] == ('Besitzer (§): §', 1000, 'rwx')


def test_9001_bob_nur_lesen():
    r = access.check(BOB, chain(SHARE))
    assert r['read'] and not r['write'] and r['cause'] == 'rechte'
    assert r['steps'][-1]['why'] == ('andere: §', 'r-x')


def test_bob_in_gruppe_1000_darf_schreiben():
    r = access.check({**BOB, 'gids': [1000]}, chain(SHARE))
    assert r['write'] and r['steps'][-1]['why'][0] == 'Gruppe des Ordners (§): §'


def test_9002_unprivilegiert_nobody():
    r = access.check(ALICE, chain(SHARE_NOBODY), unprivileged=True)
    assert r['read'] and not r['write'] and r['cause'] == 'nobody'


def test_9002_root_hat_bei_nobody_keine_sonderrechte():
    r = access.check(ROOT, chain(SHARE_NOBODY), unprivileged=True)
    assert not r['write'] and r['cause'] == 'nobody'


def test_9005_mapping_root_und_alice():
    assert access.check(ALICE, chain(SHARE), unprivileged=True)['write']
    r = access.check(ROOT, chain(SHARE), unprivileged=True)  # Besitzer abgebildet: root darf
    assert r['write'] and r['steps'][-1]['why'] == ('root darf alles',)


def test_9004_nfs_rechnung_ja_mit_hinweis():
    r = access.check(ALICE, chain(d(65534, 65534, '777')), unprivileged=True, fs_kind='nfs')
    assert r['write']  # laut Rechten ja, die UGREEN lehnt trotzdem ab (Gegenprobe kommt mit AP 2.6)
    assert any('NAS entscheidet' in h[0] for h in r['hints'])


def test_privilegiert_root_auf_nfs_squash_hinweis():
    r = access.check(ROOT, chain(d(0, 0, '777')), fs_kind='nfs')
    assert any('root_squash' in h[0] for h in r['hints'])


def test_schreibgeschuetzt_eingehaengt():
    r = access.check(ALICE, chain(SHARE), readonly=True)
    assert r['read'] and not r['write'] and r['cause'] == 'nur-lesen'


def test_weg_versperrt():
    c = chain(SHARE)
    c[1]['stat'] = d(0, 0, '700')  # /mnt ohne x für andere
    r = access.check(ALICE, c)
    assert not r['read'] and not r['write'] and r['cause'] == 'weg'
    assert r['steps'][-1]['path'] == '/mnt'


def test_acl_benutzer_und_maske():
    f = {'mode': '-rw-------', 'octal': '600', 'uid': 1000, 'gid': 1000, 'type': 'regular file'}
    acl = {'access': [{'tag': 'user_obj', 'id': None, 'perm': 'rw-'}, {'tag': 'user', 'id': 1001, 'perm': 'r--'},
                      {'tag': 'group_obj', 'id': None, 'perm': '---'}, {'tag': 'mask', 'id': None, 'perm': 'r--'},
                      {'tag': 'other', 'id': None, 'perm': '---'}]}
    r = access.check(BOB, chain(f, acl))
    assert r['read'] and not r['write']
    acl['access'][3]['perm'] = '---'  # Maske leer: ACL wirkt nicht mehr
    assert not access.check(BOB, chain(f, acl))['read']


def test_gruppe_passt_aber_verbietet_andere_zaehlt_nicht():
    st = d(1000, 2000, '707')  # Gruppe media darf nichts, andere alles
    r = access.check({**BOB, 'gids': [2000]}, chain(st))
    assert not r['read'] and r['steps'][-1]['why'][0] == 'Gruppe des Ordners (§): §'


def test_ziel_fehlt():
    assert access.check(ALICE, chain(None))['cause'] == 'fehlt'


def test_diagnose_aus_scan_9005():
    cfg = parse.pct_config((Path(__file__).parent / 'fixtures' / 'pct_config_9005.txt').read_text())
    guest = {'vmid': 9005, 'type': 'lxc', 'status': 'running', 'config': cfg, 'details': {
        'users': [{'name': 'alice', 'uid': 1000, 'gid': 1000}, {'name': 'bob', 'uid': 1001, 'gid': 1001}],
        'groups': [{'name': 'alice', 'gid': 1000, 'members': []}, {'name': 'bob', 'gid': 1001, 'members': []}],
        'stat': {'/': ROOT_DIR, '/mnt': ROOT_DIR, '/mnt/share': SHARE}}}
    # ACL vom Host: Benutzer 101001 (Host) ist im Container bob (1001)
    next(m for m in cfg['mounts'] if m['target'] == '/mnt/share')['acl'] = {
        'access': [{'tag': 'user', 'id': 101001, 'perm': 'rwx'}, {'tag': 'mask', 'id': None, 'perm': 'rwx'}]}
    assert view.diagnose(guest, 1000, '/mnt/share')['write']
    r = view.diagnose(guest, 1001, '/mnt/share')
    assert r['write'] and r['steps'][-1]['why'][0] == 'ACL für den Benutzer: §'
    assert view.diagnose(guest, 4711, '/mnt/share') is None


def test_scan_liest_uebergeordnete_ordner(monkeypatch):
    from app.pve import scan, ssh
    calls = []
    monkeypatch.setattr(ssh, 'run', lambda host, args, port=22, timeout=75: calls.append(args) or ssh.Result(0, '', ''))
    scan._details('h', 22, {'vmid': 9005, 'config': {'mounts': [{'target': '/mnt/share/a', 'source': '/x'}]}})
    assert ['pct', 'exec', '9005', '--'] + scan.STAT + ['/', '/mnt', '/mnt/share'] in calls
    assert scan.parents('/mnt/a/b') == ['/', '/mnt', '/mnt/a']


def test_diagnose_nas_aus():
    guest = {'config': {'unprivileged': True, 'mounts': [{'target': '/mnt/test', 'source': '/mnt/nfs', 'kind': 'bind'}]},
             'details': {'users': [{'name': 'alice', 'uid': 1000, 'gid': 1000}], 'groups': [], 'stat': {},
                         'offline': ['/mnt/test']}}
    assert view.diagnose(guest, 1000, '/mnt/test')['cause'] == 'offline'


def _scan_mit_9002(monkeypatch):
    from app.pve import scan
    guest = {'vmid': 9002, 'name': 'ppm-test-unpriv', 'type': 'lxc', 'status': 'running',
             'config': {'unprivileged': True, 'idmap': [], 'mounts': [
                 {'key': 'mp0', 'target': '/mnt/share', 'source': '/srv/ppm-test/share', 'kind': 'bind',
                  'host_stat': SHARE, 'fs_kind': 'lokal'}]},
             'details': {'users': [{'name': 'root', 'uid': 0, 'gid': 0}, {'name': 'alice', 'uid': 1000, 'gid': 1000},
                                   {'name': 'www-data', 'uid': 33, 'gid': 33}],
                         'groups': [], 'stat': {'/': ROOT_DIR, '/mnt': ROOT_DIR, '/mnt/share': SHARE_NOBODY}}}
    last = {'host': '10.0.0.5', 'finished': '2026-10-19T10:00:00+00:00', 'guests': [guest]}
    monkeypatch.setattr(scan, 'latest', lambda i=None: last)
    return guest


def test_diagnose_seite(client, monkeypatch):
    _scan_mit_9002(monkeypatch)
    r = client.get('/diagnose')
    assert r.status_code == 200 and '9002 · ppm-test-unpriv' in r.text
    r = client.get('/diagnose?ct=9002')  # ohne Auswahl: erster normaler Benutzer, erster Mount
    assert 'value="/mnt/share"' in r.text and '<option value="1000" selected>' in r.text
    assert 'nobody' in r.text and 'pl-no' in r.text
    assert 'Systembenutzer' in r.text and 'www-data' in r.text


def test_diagnose_seite_eigener_pfad_wird_live_gelesen(client, monkeypatch):
    from app.pve import scan, ssh
    _scan_mit_9002(monkeypatch)
    calls = []

    def run(host, args, port=22, timeout=75):
        calls.append(args)
        return ssh.Result(0, '|'.join(['drwxrwxrwx', '777', '1000', '1000', 'alice', 'alice', 'directory',
                                       '/home/alice/x']) + '\n', '')
    monkeypatch.setattr(ssh, 'run', run)
    r = client.get('/diagnose?ct=9002&uid=1000&path=/home/alice/x')
    assert calls and calls[0][-1] == '/home/alice/x' and calls[0][:4] == ['pct', 'exec', '9002', '--']
    assert 'pl-yes' in r.text
    r = client.get('/diagnose?ct=9002&uid=1000&path=/tmp/$(boese)')
    assert 'ungültig' in r.text and len(calls) == 1  # kein Aufruf mit ungültigem Pfad


def test_container_seite_hat_pruefen_links(client, monkeypatch):
    _scan_mit_9002(monkeypatch)
    r = client.get('/container/9002?tab=mounts')
    assert '/diagnose?ct=9002&amp;path=/mnt/share' in r.text
