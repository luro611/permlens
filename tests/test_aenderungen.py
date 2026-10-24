"""Phase 3, Änderungs-Baustein: Vorschau, Ausführen, Nachprüfen, Protokoll, Rückgängig (am Beispiel Gruppen)."""
import pytest

from app import db
from app.pve import change, scan, ssh
from conftest import host_id, set_pve  # noqa: E402

GUEST = {'vmid': 9003, 'name': 'ppm-test-samba', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': False, 'mounts': []},
         'details': {'users': [{'name': 'alice', 'uid': 1000, 'gid': 1000}],
                     'groups': [{'name': 'root', 'gid': 0, 'members': []},
                                {'name': 'alice', 'gid': 1000, 'members': []},
                                {'name': 'media', 'gid': 2000, 'members': ['alice']},
                                {'name': 'leer', 'gid': 2002, 'members': []}],
                     'stat': {}}}


def guest(**kw):
    return {**GUEST, **kw}


def test_vorschau_gruppe_anlegen():
    p = change.plan('gruppe-anlegen', GUEST, {'name': 'projekt', 'gid': '2001'}, '9001-9006')
    assert p['error'] is None and p['allowed']
    assert p['cmd'] == ['groupadd', '-g', '2001', 'projekt'] and p['rating'] == 'harmlos'
    assert p['pct'] == 'pct exec 9003 -- groupadd -g 2001 projekt'
    assert p['undo'] == {'action': 'gruppe-loeschen', 'params': {'name': 'projekt'}}
    assert p['undo_shell'] == 'groupdel projekt'


@pytest.mark.parametrize('params, fehler', [
    ({'name': 'Projekt', 'gid': '2001'}, 'Gruppenname ist ungültig'),
    ({'name': 'a;id', 'gid': '2001'}, 'Gruppenname ist ungültig'),
    ({'name': 'projekt', 'gid': '999'}, 'zwischen'),
    ({'name': 'projekt', 'gid': '65534'}, 'zwischen'),
    ({'name': 'projekt', 'gid': 'x'}, 'zwischen'),
    ({'name': 'media', 'gid': '2001'}, 'gibt es schon'),
    ({'name': 'projekt', 'gid': '2000'}, 'schon vergeben'),
])
def test_vorschau_gruppe_anlegen_fehler(params, fehler):
    p = change.plan('gruppe-anlegen', GUEST, params, '9001-9006')
    assert fehler in p['error'][0] and not p['cmd']


@pytest.mark.parametrize('name, fehler', [
    ('fehlt', 'gibt es in diesem Container nicht'),
    ('root', 'Systemgruppen'),
    ('alice', 'Hauptgruppe'),
    ('media', 'noch Mitglieder'),
])
def test_vorschau_gruppe_loeschen_fehler(name, fehler):
    p = change.plan('gruppe-loeschen', GUEST, {'name': name}, '9001-9006')
    assert fehler in p['error'][0]


def test_vorschau_gruppe_loeschen():
    p = change.plan('gruppe-loeschen', GUEST, {'name': 'leer'}, '9003')
    assert p['error'] is None and p['rating'] == 'vorsicht' and p['cmd'] == ['groupdel', 'leer']
    assert p['undo'] == {'action': 'gruppe-anlegen', 'params': {'name': 'leer', 'gid': '2002'}}
    assert p['undo_shell'] == 'groupadd -g 2002 leer'


def test_nicht_freigegeben_und_gestoppt():
    assert not change.plan('gruppe-anlegen', GUEST, {'name': 'projekt', 'gid': '2001'}, '9001-9002')['allowed']
    assert not change.plan('gruppe-anlegen', GUEST, {'name': 'projekt', 'gid': '2001'}, '')['allowed']
    p = change.plan('gruppe-anlegen', guest(status='stopped'), {'name': 'projekt', 'gid': '2001'}, '9003')
    assert 'läuft nicht' in p['error'][0]
    assert 'kennt PermLens nicht' in change.plan('rm-rf', GUEST, {}, '9003')['error'][0]


def test_freigabe_lesen():
    assert change.write_ranges('9001-9006,112') == [(9001, 9006), (112, 112)]
    assert change.write_allowed('9001-9006', 9004) and not change.write_allowed('9001-9006', 112)
    assert change.free_gid(GUEST, 2000) == 2001


class Proxmox:
    """Gespielter Proxmox: führt groupadd/groupdel in einer Gruppenliste aus, wie der Wächter es täte."""
    def __init__(self, write='9003'):
        self.groups = [dict(g) for g in GUEST['details']['groups']]
        self.write = write
        self.calls = []

    def __call__(self, host, args, port=22, timeout=75):
        self.calls.append(args)
        vmid, cmd = args[2], args[4:]
        if cmd == ['getent', 'group']:
            return ssh.Result(0, ''.join(f"{g['name']}:x:{g['gid']}:{','.join(g['members'])}\n" for g in self.groups), '')
        if not change.write_allowed(self.write, vmid):
            return ssh.Result(126, '', 'permlens-guard: Schreiben ist für diesen Container nicht freigegeben')
        if cmd[0] == 'groupadd':
            self.groups.append({'name': cmd[3], 'gid': int(cmd[2]), 'members': []})
        elif cmd[0] == 'groupdel':
            self.groups = [g for g in self.groups if g['name'] != cmd[1]]
        return ssh.Result(0, '', '')


@pytest.fixture
def pve(client, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_write='9003')
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [GUEST], 'error': ''})
    p = Proxmox()
    monkeypatch.setattr(ssh, 'run', p)
    monkeypatch.setattr(scan, 'start', lambda *a, **k: True)  # kein Neu-Einlesen im Test
    return p


def test_ablauf_anlegen_und_rueckgaengig(client, pve):
    form = {'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'projekt', 'gid': '2001'}
    r = client.post('/aenderung/vorschau', data=form)
    assert r.status_code == 200 and 'groupadd -g 2001 projekt' in r.text and 'Ausführen' in r.text
    assert pve.calls == []  # die Vorschau ändert nichts
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()}, follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'].startswith('/aenderungen?neu=')
    assert ['pct', 'exec', '9003', '--', 'groupadd', '-g', '2001', 'projekt'] in pve.calls
    assert any(g['name'] == 'projekt' for g in pve.groups)
    e = change.entries()[0]
    assert e['result'] == 'ok' and e['shell'] == 'groupadd -g 2001 projekt'
    assert 'Erledigt und nachgeprüft' in client.get(r.headers['location']).text

    # Rückgängig: wieder mit Vorschau, dann Ausführen
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'error': '',
               'guests': [guest(details={**GUEST['details'], 'groups': pve.groups})]})
    r = client.post(f'/aenderungen/{e["id"]}/rueckgaengig')
    assert 'groupdel projekt' in r.text and 'Rückgängig machen von Änderung' in r.text
    r = client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'gruppe-loeschen', 'vmid': '9003', 'name': 'projekt',
                                                   'undo_of': str(e['id'])}, follow_redirects=False)
    assert r.status_code == 303 and not any(g['name'] == 'projekt' for g in pve.groups)
    first = change.entry(e['id'])
    assert first['undone_by'] == change.entries()[0]['id'] and change.entries()[0]['undo_of'] == e['id']


def test_waechter_lehnt_ab(client, pve):
    pve.write = ''  # Schalter-Datei wurde auf dem Host inzwischen geleert
    r = client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'projekt',
                                                   'gid': '2001'}, follow_redirects=False)
    e = change.entries()[0]
    assert e['result'] == 'fehler' and 'nicht freigegeben' in e['detail']
    assert 'Nicht ausgeführt' in client.get(r.headers['location']).text


def test_ohne_freigabe_kein_ausfuehren(client, pve):
    set_pve(pve_write='')
    form = {'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'projekt', 'gid': '2001'}
    assert 'nicht freigegeben' in client.post('/aenderung/vorschau', data=form).text
    vorher = len(change.entries())
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()})
    assert r.status_code == 200 and pve.calls == [] and len(change.entries()) == vorher


def test_fremde_seite_wird_abgewiesen(client, pve):
    form = {'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'projekt', 'gid': '2001'}
    r = client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id()}, headers={'origin': 'https://boese.example'})
    assert 'nicht von PermLens selbst' in r.text and pve.calls == []


def test_falsche_eingabe_wird_beim_ausfuehren_neu_geprueft(client, pve):
    r = client.post('/aenderung/ausfuehren', data={'host_id': host_id(), 'action': 'gruppe-anlegen', 'vmid': '9003', 'name': 'root;id',
                                                   'gid': '2001'})
    assert 'Gruppenname ist ungültig' in r.text and pve.calls == []


def test_container_seite_zeigt_gruppen_und_formular(client, pve):
    r = client.get('/container/9003?tab=benutzer')
    assert 'Neue Gruppe …' in r.text and 'value="2001"' in r.text and 'Gruppe löschen …' in r.text
    set_pve(pve_write='')
    r = client.get('/container/9003?tab=benutzer')
    assert 'Neue Gruppe' not in r.text and 'Ändern ist ausgeschaltet' in r.text
    assert "echo &#39;9003&#39; &gt;&gt; /etc/permlens/schreiben-erlaubt" in r.text or "echo '9003' &gt;&gt; /etc/permlens/schreiben-erlaubt" in r.text
