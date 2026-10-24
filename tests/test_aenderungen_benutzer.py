"""Phase 3, AP 3.5: Benutzer anlegen und löschen, Mitgliedschaften und Hauptgruppe im LXC."""
import pytest

from app import db
from app.pve import change, scan, ssh
from conftest import host_id, set_pve  # noqa: E402

ST = {'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 2000, 'user': 'alice', 'group': 'media',
      'type': 'directory'}
ROOT = {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 0, 'gid': 0, 'type': 'directory'}
USERS = [{'name': 'root', 'uid': 0, 'gid': 0}, {'name': 'sshd', 'uid': 991, 'gid': 65534},
         {'name': 'alice', 'uid': 1000, 'gid': 1000}, {'name': 'bob', 'uid': 1001, 'gid': 1001}]
GROUPS = [{'name': 'root', 'gid': 0, 'members': []}, {'name': 'sudo', 'gid': 27, 'members': []},
          {'name': 'alice', 'gid': 1000, 'members': []}, {'name': 'bob', 'gid': 1001, 'members': []},
          {'name': 'media', 'gid': 2000, 'members': ['alice']}]
GUEST = {'vmid': 9003, 'name': 'ppm-test-samba', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': False, 'mounts': [{'key': 'mp0', 'source': '/srv/x', 'target': '/mnt/share', 'kind': 'bind'}]},
         'details': {'users': USERS, 'groups': GROUPS, 'stat': {'/': ROOT, '/mnt': ROOT, '/mnt/share': ST}}}


def plan(action, **params):
    return change.plan(action, GUEST, params, '9001-9006')


def test_mitglied_hinzu_mit_folgen():
    p = plan('mitglied-hinzu', user='bob', group='media')
    assert p['error'] is None and p['cmd'] == ['usermod', '-aG', 'media', 'bob'] and p['rating'] == 'vorsicht'
    assert p['undo_shell'] == 'gpasswd -d bob media'
    assert {'user': 'bob · /mnt/share', 'uid': 1001, 'what': 'write', 'after': True} in p['effects']
    assert ('Weitere Gruppen von §: §', 'bob', 'media') in p['after']


def test_mitglied_weg():
    p = plan('mitglied-weg', user='alice', group='media')
    assert p['cmd'] == ['gpasswd', '-d', 'alice', 'media'] and p['undo_shell'] == 'usermod -aG media alice'


@pytest.mark.parametrize('action, params, fehler', [
    ('mitglied-hinzu', {'user': 'bob', 'group': 'sudo'}, 'Systemgruppen'),
    ('mitglied-hinzu', {'user': 'root', 'group': 'media'}, 'Systembenutzer'),
    ('mitglied-hinzu', {'user': 'sshd', 'group': 'media'}, 'Systembenutzer'),
    ('mitglied-hinzu', {'user': 'alice', 'group': 'media'}, 'schon in der Gruppe'),
    ('mitglied-hinzu', {'user': 'alice', 'group': 'alice'}, 'schon in der Gruppe'),  # Hauptgruppe
    ('mitglied-hinzu', {'user': 'eve', 'group': 'media'}, 'gibt es in diesem Container nicht'),
    ('mitglied-weg', {'user': 'bob', 'group': 'media'}, 'nicht als weiteres Mitglied'),
    ('benutzer-anlegen', {'name': 'dave', 'uid': '1000', 'gid': '2000'}, 'hat schon der Benutzer'),
    ('benutzer-anlegen', {'name': 'bob', 'uid': '1005', 'gid': '2000'}, 'gibt es schon'),
    ('benutzer-anlegen', {'name': 'dave', 'uid': '0', 'gid': '2000'}, 'zwischen'),
    ('benutzer-anlegen', {'name': 'dave', 'uid': '1005', 'gid': '3000'}, 'Erst unter „Gruppen“ anlegen'),
    ('benutzer-anlegen', {'name': 'Dave!', 'uid': '1005', 'gid': '2000'}, 'Benutzername ist ungültig'),
    ('benutzer-loeschen', {'name': 'alice'}, 'noch in den Gruppen'),
    ('benutzer-loeschen', {'name': 'root'}, 'Systembenutzer'),
    ('hauptgruppe', {'user': 'bob', 'gid': '27'}, 'gibt es nicht'),
    ('hauptgruppe', {'user': 'bob', 'gid': '1001'}, 'schon die Hauptgruppe'),
])
def test_fehler(action, params, fehler):
    p = plan(action, **params)
    assert fehler in p['error'][0] and not p['cmd']


def test_benutzer_anlegen_und_loeschen():
    p = plan('benutzer-anlegen', name='dave', uid='1005', gid='2000')
    assert p['cmd'] == ['useradd', '-m', '-u', '1005', '-g', '2000', 'dave'] and p['undo_shell'] == 'userdel dave'
    p = plan('benutzer-loeschen', name='bob')
    assert p['cmd'] == ['userdel', 'bob'] and p['rating'] == 'risiko'
    assert p['undo_shell'] == 'useradd -m -u 1001 -g 1001 bob'


def test_hauptgruppe():
    p = plan('hauptgruppe', user='bob', gid='2000')
    assert p['cmd'] == ['usermod', '-g', '2000', 'bob'] and p['undo_shell'] == 'usermod -g 1001 bob'
    assert any(e['user'] == 'bob · /mnt/share' and e['what'] == 'write' and e['after'] for e in p['effects'])


def test_freie_nummern():
    assert change.free_uid(GUEST, 1000) == 1002


class Proxmox:
    def __init__(self):
        self.users = [dict(u) for u in USERS]
        self.groups = [dict(g, members=list(g['members'])) for g in GROUPS]
        self.calls = []

    def __call__(self, host, args, port=22, timeout=75):
        self.calls.append(args)
        cmd = args[4:]
        if cmd == ['getent', 'passwd']:
            return ssh.Result(0, ''.join(f"{u['name']}:x:{u['uid']}:{u['gid']}::/home/{u['name']}:/bin/sh\n" for u in self.users), '')
        if cmd == ['getent', 'group']:
            return ssh.Result(0, ''.join(f"{g['name']}:x:{g['gid']}:{','.join(g['members'])}\n" for g in self.groups), '')
        grp = {g['name']: g for g in self.groups}
        if cmd[:2] == ['usermod', '-aG']:
            grp[cmd[2]]['members'].append(cmd[3])
        elif cmd[:2] == ['gpasswd', '-d']:
            grp[cmd[3]]['members'].remove(cmd[2])
        elif cmd[:2] == ['usermod', '-g']:
            next(u for u in self.users if u['name'] == cmd[3])['gid'] = int(cmd[2])
        elif cmd[0] == 'useradd':
            self.users.append({'name': cmd[6], 'uid': int(cmd[3]), 'gid': int(cmd[5])})
        elif cmd[0] == 'userdel':
            self.users = [u for u in self.users if u['name'] != cmd[1]]
        return ssh.Result(0, '', '')


@pytest.fixture
def pve(client, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_write='9001-9006', pve_guard='6')
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [GUEST], 'error': ''})
    p = Proxmox()
    monkeypatch.setattr(ssh, 'run', p)
    monkeypatch.setattr(scan, 'start', lambda *a, **k: True)
    return p


def test_ablauf_mitglied_und_rueckgaengig(client, pve):
    form = {'action': 'mitglied-hinzu', 'vmid': '9003', 'user': 'bob', 'group': 'media'}
    assert 'usermod -aG media bob' in client.post('/aenderung/vorschau', data=form).text
    client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()})
    e = change.entries()[0]
    assert e['result'] == 'ok' and 'bob' in next(g for g in pve.groups if g['name'] == 'media')['members']
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'error': '',
               'guests': [{**GUEST, 'details': {**GUEST['details'], 'groups': pve.groups}}]})
    assert 'gpasswd -d bob media' in client.post(f'/aenderungen/{e["id"]}/rueckgaengig').text
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'mitglied-weg', 'vmid': '9003', 'user': 'bob',
                                               'group': 'media', 'undo_of': str(e['id'])})
    assert change.entries()[0]['result'] == 'ok' and change.entry(e['id'])['undone_by']


def test_ablauf_benutzer_anlegen(client, pve):
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'benutzer-anlegen', 'vmid': '9003', 'name': 'dave',
                                               'uid': '1005', 'gid': '2000'})
    assert change.entries()[0]['result'] == 'ok' and any(u['name'] == 'dave' for u in pve.users)


def test_benutzer_loeschen_braucht_containernummer(client, pve):
    form = {'action': 'benutzer-loeschen', 'vmid': '9003', 'name': 'bob'}
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()})
    assert 'Container-Nummer eintippen' in r.text and any(u['name'] == 'bob' for u in pve.users)
    client.post('/aenderung/ausfuehren', data={'host_id': host_id(), **form, 'confirm': '9003'})
    assert not any(u['name'] == 'bob' for u in pve.users)


def test_container_seite_zeigt_formulare(client, pve):
    r = client.get('/container/9003?tab=benutzer')
    assert 'Neuer Benutzer …' in r.text and 'value="hauptgruppe"' in r.text and 'value="mitglied-weg"' in r.text and 'value="1002"' in r.text
