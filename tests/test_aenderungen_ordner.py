"""Phase 3, AP 3.3 und 3.4: Besitzer, Rechte, ACL eines Ordners und der echte Schreibtest."""
import pytest

from app import db
from app.pve import change, parse, scan, ssh
from conftest import host_id, set_pve  # noqa: E402

ST = {'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 1000, 'user': 'alice', 'group': 'alice',
      'type': 'directory'}
GUEST = {'vmid': 9005, 'name': 'ppm-test-idmap', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': True, 'mounts': [{'key': 'mp1', 'source': '/srv/ppm-test/share', 'target': '/mnt/share',
                                                      'kind': 'bind'}]},
         'details': {'users': [{'name': 'root', 'uid': 0, 'gid': 0}, {'name': 'alice', 'uid': 1000, 'gid': 1000},
                               {'name': 'bob', 'uid': 1001, 'gid': 1001}],
                     'groups': [{'name': 'alice', 'gid': 1000, 'members': []}, {'name': 'bob', 'gid': 1001, 'members': []},
                                {'name': 'media', 'gid': 2000, 'members': ['alice']}],
                     'stat': {'/mnt/share': ST}}}
ROOTS = {'/': {**ST, 'octal': '755', 'uid': 0, 'gid': 0}, '/mnt': {**ST, 'octal': '755', 'uid': 0, 'gid': 0}}


def state(st=None, acl=()):
    return {'stat': st or ST, 'stats': {**ROOTS, '/mnt/share': st or ST}, 'acl': list(acl), 'error': None,
            'acl_missing': False}


def plan(action, state_=None, **params):
    return change.plan(action, GUEST, {'path': '/mnt/share', **params}, '9001-9006', state_ or state())


def test_besitzer():
    p = plan('besitzer', uid='1001', gid='2000')
    assert p['error'] is None and p['cmd'] == ['chown', '1001:2000', '/mnt/share'] and p['rating'] == 'vorsicht'
    assert p['undo'] == {'action': 'besitzer', 'params': {'path': '/mnt/share', 'uid': '1000', 'gid': '1000'}}
    assert p['undo_shell'] == 'chown 1000:1000 /mnt/share'
    assert ('Besitzer und Gruppe: §', '1000:1000 (alice:alice)') in p['before']
    # alice verliert Schreiben (nicht mehr Besitzerin, aber über media weiter Gruppe), bob gewinnt
    eff = {(e['user'], e['what']): e['after'] for e in p['effects']}
    assert eff.get(('bob', 'write')) is True


def test_nobody_im_unprivilegierten_container_geht_nicht():
    for action, params in (('besitzer', {'uid': '1000', 'gid': '1000'}), ('rechte', {'mode': '777'}),
                           ('acl-setzen', {'kind': 'u', 'id': '1000', 'perm': 'rwx'})):
        p = plan(action, state(dict(ST, uid=65534, gid=65534)), **params)
        assert 'nobody' in p['error'][0] and not p['cmd']


def test_besitzer_nobody_privilegiert_ist_risiko_ohne_rueckgaengig():
    priv = {**GUEST, 'config': {**GUEST['config'], 'unprivileged': False}}
    p = change.plan('besitzer', priv, {'path': '/mnt/share', 'uid': '1000', 'gid': '1000'}, '9001-9006',
                    state(dict(ST, uid=65534, gid=65534)))
    assert p['rating'] == 'risiko' and p['undo'] is None and p['undo_shell'] == ''


@pytest.mark.parametrize('params, fehler', [
    ({'uid': 'alice', 'gid': '1000'}, 'Nummern'),
    ({'uid': '65534', 'gid': '1000'}, 'Nummern'),
    ({'uid': '1000', 'gid': '1000'}, 'nichts zu ändern'),
])
def test_besitzer_fehler(params, fehler):
    assert fehler in plan('besitzer', **params)['error'][0]


@pytest.mark.parametrize('path', ['/etc', '/mnt', '/', '/mnt/sharex', '/mnt/share/../etc', 'relativ'])
def test_nur_eingehaengte_ordner(path):
    p = change.plan('rechte', GUEST, {'path': path, 'mode': '755'}, '9001-9006', state())
    assert 'eingehängten Ordnern' in p['error'][0] and not p['cmd']


def test_home_ist_erlaubt():
    assert change.path_ok(GUEST, '/home/alice') and not change.path_ok(GUEST, '/home2')


def test_rechte_zahl_und_setgid():
    p = plan('rechte', mode='755')
    # Ordner mit setgid: zum Entfernen braucht chmod eine führende 0
    assert p['cmd'] == ['chmod', '00755', '/mnt/share'] and p['undo']['params']['mode'] == '2775'
    assert ('Rechte: §', '2775 (rwxrwsr-x)') in p['before'] and ('Rechte: §', '755 (rwxr-xr-x)') in p['after']


def test_rechte_symbolisch():
    p = plan('rechte', state(dict(ST, octal='2755')), add='g+w')
    assert p['cmd'] == ['chmod', '2775', '/mnt/share'] and p['rating'] == 'vorsicht'


def test_rechte_fuer_alle_schreibbar_ist_risiko():
    assert plan('rechte', mode='777')['rating'] == 'risiko'


@pytest.mark.parametrize('params', [{'mode': '4755'}, {'mode': 'g+w'}, {'mode': '99'}, {'add': 'a+w'}, {'add': 'g=w'}])
def test_rechte_fehler(params):
    assert plan('rechte', **params)['error']


def test_rechte_mode_arg():
    assert change.mode_arg(0o755, 0o750, True) == '750'
    assert change.mode_arg(0o755, 0o2775, True) == '2775'
    assert change.mode_arg(0o2775, 0o775, False) == '775'  # Datei: setgid fällt mit kurzer Zahl weg


def test_acl_setzen_und_rueckgaengig():
    p = plan('acl-setzen', kind='u', id='1001', perm='r-x')
    assert p['cmd'] == ['setfacl', '-m', 'u:1001:r-x', '/mnt/share']
    assert p['undo_shell'] == 'setfacl -b /mnt/share'  # vorher gar keine ACL: ganz zurück, ohne Maske
    assert p['undo'] == {'action': 'acl-entfernen', 'params': {'path': '/mnt/share', 'kind': 'u', 'id': '1001'}}
    p = plan('acl-setzen', state(acl=[{'tag': 'user', 'id': 1001, 'perm': 'r--'}]), kind='u', id='1001', perm='rwx')
    assert p['undo']['action'] == 'acl-setzen' and p['undo']['params']['perm'] == 'r--'
    assert {(e['user'], e['what']): e['after'] for e in p['effects']}.get(('bob', 'write')) is True


def test_acl_entfernen():
    s = state(acl=[{'tag': 'group', 'id': 2000, 'perm': 'rwx'}, {'tag': 'mask', 'id': None, 'perm': 'rwx'}])
    p = plan('acl-entfernen', s, kind='g', id='2000')
    assert p['cmd'] == ['setfacl', '-b', '/mnt/share'] and p['undo']['params']['perm'] == 'rwx'
    s = state(acl=[{'tag': 'group', 'id': 2000, 'perm': 'rwx'}, {'tag': 'user', 'id': 1001, 'perm': 'r-x'}])
    assert plan('acl-entfernen', s, kind='g', id='2000')['cmd'] == ['setfacl', '-x', 'g:2000', '/mnt/share']
    assert 'keinen ACL-Eintrag' in plan('acl-entfernen', kind='g', id='2000')['error'][0]


def test_acl_ohne_paket():
    s = {**state(), 'acl': None, 'acl_missing': True}
    assert 'Paket acl' in plan('acl-setzen', s, kind='u', id='1001', perm='rwx')['error'][0]


def test_getfacl_lesen():
    text = ('user::rwx\nuser:1001:r-x\t#effective:r-x\ngroup::r-x\ngroup:2000:rwx\nmask::rwx\nother::r-x\n'
            'default:user::rwx\n')
    acl = parse.getfacl(text)
    assert {'tag': 'user', 'id': 1001, 'perm': 'r-x'} in acl and {'tag': 'mask', 'id': None, 'perm': 'rwx'} in acl
    assert len(acl) == 6


class Proxmox:
    """Gespielter Container für einen Ordner: stat, getfacl, chown/chmod/setfacl und Schreibtest."""
    def __init__(self, deny_touch=False):
        self.st = dict(ST)
        self.acl = []
        self.calls = []
        self.files = set()
        self.deny_touch = deny_touch

    def stat_line(self, path, st):
        return f"{st['mode']}|{st['octal']}|{st['uid']}|{st['gid']}|x|y|{'Verzeichnis' if False else 'directory'}|{path}\n"

    def __call__(self, host, args, port=22, timeout=75):
        self.calls.append(args)
        cmd = args[4:]
        if cmd[0] == 'stat':
            out = ''.join(self.stat_line(q, ROOTS[q]) for q in cmd[3:] if q in ROOTS)
            out += self.stat_line('/mnt/share', self.st) if '/mnt/share' in cmd else ''
            return ssh.Result(0, out, '')
        if cmd[0] == 'getfacl':
            return ssh.Result(0, ''.join(f"{'user' if e['tag'] == 'user' else 'group'}:{e['id']}:{e['perm']}\n"
                                         for e in self.acl), '')
        if cmd[0] == 'chown':
            u, g = cmd[1].split(':')
            self.st.update(uid=int(u), gid=int(g))
        elif cmd[0] == 'chmod':
            self.st['octal'] = f'{int(cmd[1], 8):o}'
        elif cmd[:2] == ['setfacl', '-b']:
            self.acl = []
        elif cmd[0] == 'setfacl':
            kind, xid = cmd[2].split(':')[:2]
            tag = 'user' if kind == 'u' else 'group'
            self.acl = [e for e in self.acl if not (e['tag'] == tag and e['id'] == int(xid))]
            if cmd[1] == '-m':
                self.acl.append({'tag': tag, 'id': int(xid), 'perm': cmd[2].split(':')[2]})
        elif cmd[0] == 'setpriv' and cmd[5] == 'touch':
            if self.deny_touch:
                return ssh.Result(1, '', "touch: cannot touch 'x': Permission denied")
            self.files.add(cmd[6])
        elif 'rm' in cmd:
            self.files.discard(cmd[-1])
        return ssh.Result(0, '', '')


@pytest.fixture
def pve(client, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_write='9001-9006', pve_guard='5')
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [GUEST], 'error': ''})
    p = Proxmox()
    monkeypatch.setattr(ssh, 'run', p)
    monkeypatch.setattr(scan, 'start', lambda *a, **k: True)
    return p


def test_ablauf_rechte_mit_rueckgaengig(client, pve):
    form = {'action': 'rechte', 'vmid': '9005', 'path': '/mnt/share', 'mode': '750'}
    r = client.post('/aenderung/vorschau', data=form)
    assert 'chmod 00750 /mnt/share' in r.text and 'chmod 2775 /mnt/share' in r.text
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()}, follow_redirects=False)
    assert pve.st['octal'] == '750'
    e = change.entries()[0]
    assert e['result'] == 'ok' and e['shell'] == 'chmod 00750 /mnt/share'
    r = client.post(f'/aenderungen/{e["id"]}/rueckgaengig')
    assert 'chmod 2775 /mnt/share' in r.text
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'rechte', 'vmid': '9005', 'path': '/mnt/share',
                                               'mode': '2775', 'undo_of': str(e['id'])})
    assert pve.st['octal'] == '2775' and change.entry(e['id'])['undone_by']


def test_ablauf_acl(client, pve):
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'acl-setzen', 'vmid': '9005', 'path': '/mnt/share',
                                               'kind': 'u', 'id': '1001', 'perm': 'rwx'})
    assert pve.acl == [{'tag': 'user', 'id': 1001, 'perm': 'rwx'}] and change.entries()[0]['result'] == 'ok'


def test_abweichung_wird_gemeldet(client, pve, monkeypatch):
    real = pve.__call__

    def lazy(host, args, port=22, timeout=75):  # Befehl „klappt“, ändert aber nichts
        return ssh.Result(0, '', '') if args[4] == 'chown' else real(host, args, port, timeout)
    monkeypatch.setattr(ssh, 'run', lazy)
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'besitzer', 'vmid': '9005', 'path': '/mnt/share',
                                               'uid': '1001', 'gid': '1001'})
    assert change.entries()[0]['result'] == 'abweichung'


def test_diagnose_zeigt_knoepfe_und_formulare(client, pve):
    st = dict(ST, octal='2755', mode='drwxr-sr-x')  # Gruppe darf nicht schreiben → Empfehlung chmod g+w
    det = {**GUEST['details'], 'stat': {'/mnt/share': st}}
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'error': '', 'guests': [{**GUEST, 'details': det}]})
    r = client.get('/diagnose?ct=9005&uid=1001&path=/mnt/share')
    assert 'Echter Schreibtest' in r.text and 'Selbst ändern: Besitzer, Rechte, ACL' in r.text
    assert 'Mit PermLens ausführen' in r.text and 'name="add" value="g+w"' in r.text
    set_pve(pve_write='')
    r = client.get('/diagnose?ct=9005&uid=1001&path=/mnt/share')
    assert 'Echter Schreibtest' not in r.text and 'Mit PermLens ausführen' not in r.text
    assert 'Ändern ist ausgeschaltet' in r.text and 'So schaltest du es frei' in r.text


def test_schreibtest_klappt_und_raeumt_auf(client, pve):
    r = client.post('/diagnose/schreibtest', data={'ct': '9005', 'uid': '1000', 'path': '/mnt/share'})
    assert 'Schreiben klappt wirklich.' in r.text and pve.files == set()
    touch = next(a for a in pve.calls if 'touch' in a)
    assert touch[:9] == ['pct', 'exec', '9005', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--groups=1000,2000', '--']
    assert touch[10].startswith('/mnt/share/.permlens-schreibtest-')


def test_schreibtest_abgelehnt(client, pve):
    pve.deny_touch = True
    r = client.post('/diagnose/schreibtest', data={'ct': '9005', 'uid': '1001', 'path': '/mnt/share'})
    assert 'Schreiben klappt wirklich nicht.' in r.text and 'Permission denied' in r.text


def test_schreibtest_nur_mit_freigabe(client, pve):
    set_pve(pve_write='')
    client.post('/diagnose/schreibtest', data={'ct': '9005', 'uid': '1000', 'path': '/mnt/share'})
    assert not any('touch' in a for a in pve.calls)
