"""Phase 3, AP 3.6 und 3.7: UID/GID ändern, umnummerieren, rekursiv mit Sicherung und Wiederherstellen."""
import pytest

from app import db
from app.pve import change, scan, ssh
from conftest import host_id, set_pve  # noqa: E402

ST = {'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 2000, 'type': 'directory'}
ROOT = {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 0, 'gid': 0, 'type': 'directory'}
USERS = [{'name': 'root', 'uid': 0, 'gid': 0}, {'name': 'alice', 'uid': 1000, 'gid': 1000},
         {'name': 'bob', 'uid': 1001, 'gid': 1001}]
GROUPS = [{'name': 'root', 'gid': 0, 'members': []}, {'name': 'alice', 'gid': 1000, 'members': []},
          {'name': 'bob', 'gid': 1001, 'members': []}, {'name': 'media', 'gid': 2000, 'members': ['alice']}]
GUEST = {'vmid': 9001, 'name': 'ppm-test-priv', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': False, 'mounts': [{'key': 'mp1', 'source': '/srv/x', 'target': '/mnt/share', 'kind': 'bind'}]},
         'details': {'users': USERS, 'groups': GROUPS, 'stat': {'/': ROOT, '/mnt': ROOT, '/mnt/share': ST}}}


def state(n=1234, **kw):
    return {'stat': ST, 'stats': {'/': ROOT, '/mnt': ROOT, '/mnt/share': ST}, 'acl': [], 'error': None,
            'acl_missing': False, 'count': n, **kw}


def plan(action, state_=None, **params):
    return change.plan(action, GUEST, params, '9001-9006', state_ if state_ is not None else state())


def test_besitzer_rekursiv():
    p = plan('besitzer-r', path='/mnt/share', uid='1001', gid='2000')
    assert p['cmd'] == ['chown', '-R', '-h', '1001:2000', '/mnt/share'] and p['rating'] == 'risiko'
    assert p['undo']['action'] == 'wiederherstellen' and 'restore' in p['undo_shell']
    assert ('Betrifft § Dateien und Ordner unter § (ohne andere Dateisysteme darunter, symbolische Verknüpfungen '
            'werden nicht verfolgt).', 1234, '/mnt/share') in p['info']


@pytest.mark.parametrize('mode, ok', [('g+rwX,o-rwx', True), ('g+s', False), ('2775', True), ('u+s', False),
                                      ('a+w', False), ('g=rw', False), ('', False)])
def test_rechte_rekursiv(mode, ok):
    p = plan('rechte-r', path='/mnt/share', mode=mode)
    assert (p['error'] is None) == ok
    if ok:
        assert p['cmd'] == ['chmod', '-R', mode, '/mnt/share']


def test_rechte_rekursiv_folgen_fuer_den_ordner():
    p = plan('rechte-r', path='/mnt/share', mode='o-rwx')
    assert p['new_stat']['octal'] == '2770'
    assert {(e['user'], e['what']): e['after'] for e in p['effects']}.get(('bob', 'read')) is False


def test_acl_rekursiv_und_standard():
    p = plan('acl-r', path='/mnt/share', kind='g', id='2000', perm='rwx')
    assert p['cmd'] == ['setfacl', '-R', '-m', 'g:2000:rwx', '/mnt/share']
    p = plan('acl-r', path='/mnt/share', kind='g', id='2000', perm='rwx', default='1')
    assert p['cmd'] == ['setfacl', '-R', '-d', '-m', 'g:2000:rwx', '/mnt/share']


def test_zu_viele_dateien():
    p = plan('besitzer-r', state(change.MAX_FILES + 1), path='/mnt/share', uid='1001', gid='2000')
    assert 'Unterordner' in p['error'][0]


def test_zaehlen_gescheitert():
    p = plan('besitzer-r', state(None), path='/mnt/share', uid='1001', gid='2000')
    assert 'gezählt' in p['error'][0]


def test_uid_aendern():
    p = plan('uid-aendern', {'mounts': [('/mnt/share', 812)]}, user='bob', uid='1005')
    assert p['cmd'] == ['usermod', '-u', '1005', 'bob'] and p['rating'] == 'risiko'
    assert p['undo_shell'] == 'usermod -u 1001 bob'
    assert ('In § gehören § Dateien der Nummer §.', '/mnt/share', 812, 1001) in p['info']
    assert 'hat schon der Benutzer' in plan('uid-aendern', {}, user='bob', uid='1000')['error'][0]
    assert 'Systembenutzer' in plan('uid-aendern', {}, user='root', uid='1005')['error'][0]


def test_gid_aendern():
    p = plan('gid-aendern', {}, group='media', gid='2010')
    assert p['cmd'] == ['groupmod', '-g', '2010', 'media'] and p['undo_shell'] == 'groupmod -g 2000 media'


def test_umnummerieren():
    p = plan('umnummerieren', {'old': 812, 'new': 0}, path='/mnt/share', kind='u', old='1001', new='1005')
    assert p['cmd'] == ['find', '/mnt/share', '-xdev', '-user', '1001', '-exec', 'chown', '-h', '1005', '{}', '+']
    assert p['undo']['params'] == {'path': '/mnt/share', 'kind': 'u', 'old': '1005', 'new': '1001'}
    p = plan('umnummerieren', {'old': 3, 'new': 0}, path='/mnt/share', kind='g', old='2000', new='2010')
    assert p['cmd'][3:7] == ['-group', '2000', '-exec', 'chgrp']


@pytest.mark.parametrize('counts, fehler', [({'old': 0, 'new': 0}, 'keine Datei'),
                                            ({'old': 5, 'new': 2}, 'nicht sauber rückgängig'),
                                            ({'old': None, 'new': 0}, 'gezählt')])
def test_umnummerieren_fehler(counts, fehler):
    assert fehler in plan('umnummerieren', counts, path='/mnt/share', kind='u', old='1001', new='1005')['error'][0]


BACKUP = '# file: /mnt/share\n# owner: 1000\n# group: 2000\n# flags: -s-\nuser::rwx\ngroup::rwx\nother::r-x\n\n'


class Proxmox:
    """Gespielter Container: ein Ordner mit Besitzer; zählt, sichert und spielt zurück."""
    def __init__(self):
        self.st = dict(ST)
        self.calls, self.inputs = [], []
        self.fail_backup = False

    def __call__(self, host, args, port=22, timeout=75, data=None):
        self.calls.append(args)
        self.inputs.append(data)
        cmd = args[4:]
        if cmd[0] == 'stat':
            line = lambda p, s: f"{s['mode']}|{s['octal']}|{s['uid']}|{s['gid']}|x|y|directory|{p}\n"  # noqa: E731
            out = ''.join(line(q, ROOT) for q in cmd[3:] if q in ('/', '/mnt'))
            return ssh.Result(0, out + (line('/mnt/share', self.st) if '/mnt/share' in cmd else ''), '')
        if cmd[0] == 'getfacl' and '-R' in cmd:
            if self.fail_backup:
                return ssh.Result(1, '', 'getfacl: not found')
            return ssh.Result(0, BACKUP.replace('1000', str(self.st['uid'])).replace('2000', str(self.st['gid'])), '')
        if cmd[0] == 'getfacl':
            return ssh.Result(0, '', '')
        if cmd[0] == 'find' and cmd[-2:] == ['-printf', '.']:
            return ssh.Result(0, '.' * 1234, '')
        if cmd[:3] == ['chown', '-R', '-h']:
            u, g = cmd[3].split(':')
            self.st.update(uid=int(u), gid=int(g))
        if cmd[0] == 'permlens-restore':
            self.st.update(uid=1000, gid=2000)
        return ssh.Result(0, '', '')


@pytest.fixture
def pve(client, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_write='9001-9006', pve_guard='7')
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [GUEST], 'error': ''})
    p = Proxmox()
    monkeypatch.setattr(ssh, 'run', p)
    monkeypatch.setattr(scan, 'start', lambda *a, **k: True)
    return p


def test_ablauf_rekursiv_mit_sicherung_und_rueckgaengig(client, pve):
    form = {'action': 'besitzer-r', 'vmid': '9001', 'path': '/mnt/share', 'uid': '1001', 'gid': '1001'}
    r = client.post('/aenderung/vorschau', data=form)
    assert '1234' in r.text and 'Container-Nummer eintippen' in r.text
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()})
    assert 'Container-Nummer eintippen' in r.text and pve.st['uid'] == 1000  # ohne Bestätigung nichts
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), **form, 'confirm': '9001'})
    e = change.entries()[0]
    assert e['result'] == 'ok' and pve.st['uid'] == 1001
    assert e['backup'] == BACKUP and e['undo'] == {'action': 'wiederherstellen', 'params': {'path': '/mnt/share', 'nr': str(e['id'])}}
    getfacl = next(i for i, a in enumerate(pve.calls) if a[4:6] == ['getfacl', '-R'])
    chown = next(i for i, a in enumerate(pve.calls) if a[4:6] == ['chown', '-R'])
    assert getfacl < chown  # erst sichern, dann ändern

    r = client.post(f'/aenderungen/{e["id"]}/rueckgaengig')
    assert 'Sicherung zurückspielen' in r.text
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'wiederherstellen', 'vmid': '9001', 'path': '/mnt/share',
                                               'nr': str(e['id']), 'undo_of': str(e['id'])})
    restore = next(i for i, a in enumerate(pve.calls) if a[4:5] == ['permlens-restore'])
    assert pve.inputs[restore] == BACKUP and pve.st['uid'] == 1000
    assert change.entries()[0]['result'] == 'ok' and change.entry(e['id'])['undone_by']


def test_ohne_sicherung_keine_aenderung(client, pve):
    pve.fail_backup = True
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'besitzer-r', 'vmid': '9001', 'path': '/mnt/share',
                                               'uid': '1001', 'gid': '1001', 'confirm': '9001'})
    e = change.entries()[0]
    assert e['result'] == 'fehler' and 'Sicherung' in e['detail'] and pve.st['uid'] == 1000
    assert not any(a[4:6] == ['chown', '-R'] for a in pve.calls)


def test_seiten_zeigen_formulare(client, pve):
    assert 'Ganzer Ordner mit allem darunter' in client.get('/diagnose?ct=9001&uid=1001&path=/mnt/share').text
    r = client.get('/container/9001?tab=ordner')
    assert 'Dateien umnummerieren …' in r.text and 'value="umnummerieren"' in r.text and '#selbst' in r.text
    assert 'value="uid-aendern"' in client.get('/container/9001?tab=benutzer').text
