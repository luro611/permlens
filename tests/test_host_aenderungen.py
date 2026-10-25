"""AP 6.5: Änderungen am Host (Mount-Punkte, Mapping) mit Vorschau, Ausführen über den echten Wächter 9 und Rückgängig.

Der gespielte Proxmox lässt jeden Befehl durch das echte Wächter-Script laufen; nur pct und cat auf dem Host sind
nachgebaut (pct set schreibt in die conf-Datei, wie Proxmox es täte)."""
import contextlib
import io
import shlex
import subprocess

import pytest

from app import db
from app.pve import change, hostchange, parse, scan, ssh
from conftest import host_id, set_pve  # noqa: E402
from test_waechter import g

ST = {'uid': 1000, 'gid': 1000, 'mode': 'drwxrwxr-x', 'octal': '775', 'type': 'directory'}
CONF = 'arch: amd64\nhostname: ppm-test-share\nmp0: /srv/ppm-test/share,mp=/mnt/share\nunprivileged: 1\n'
GUEST = {'vmid': 9002, 'name': 'ppm-test-share', 'type': 'lxc', 'status': 'stopped',
         'config': {**parse.pct_config(CONF), 'mounts': [{**parse.pct_config(CONF)['mounts'][0], 'host_stat': ST}]},
         'details': None}


class Host:
    """Gespielter Proxmox mit dem echten Wächter."""
    def __init__(self, tmp, monkeypatch):
        self.tmp, self.status, self.calls = tmp, 'stopped', []
        (tmp / 'lxc').mkdir()
        (tmp / 'lxc' / '9002.conf').write_text(CONF + '\n[vorher]\nhostname: alt\n')
        (tmp / 'lxc' / '9003.conf').write_text('hostname: andere\nmp0: /srv/ppm-test/samba,mp=/srv/samba\n')
        (tmp / 'freigabe' / 'neu').mkdir(parents=True)
        (tmp / 'host-aendern-erlaubt').write_text(f'9001-9006\n{tmp / "freigabe"}\n')
        (tmp / 'subuid').write_text('root:100000:65536\n')
        (tmp / 'subgid').write_text('root:100000:65536\n')
        for k, v in {'CONF_DIR': str(tmp / 'lxc'), 'HOST_FILE': str(tmp / 'host-aendern-erlaubt'),
                     'WRITE_FILE': str(tmp / 'schreiben-erlaubt'), 'BACKUP_DIR': str(tmp / 'sicherung'),
                     'SUBID_FILES': {'subuid': str(tmp / 'subuid'), 'subgid': str(tmp / 'subgid')},
                     'log': lambda t: None}.items():
            monkeypatch.setattr(g, k, v)
        monkeypatch.setattr(g.subprocess, 'run', self.system)
        monkeypatch.setattr(ssh, 'run', self.ssh)

    def conf(self, vmid='9002'):
        return (self.tmp / 'lxc' / f'{vmid}.conf').read_text()

    def system(self, args, **kw):
        """pct und cat auf dem Host."""
        conf = self.tmp / 'lxc' / f'{args[2] if len(args) > 2 else ""}.conf'
        out = ''
        if args[:2] == ['pct', 'status']:
            out = f'status: {self.status}\n'
        elif args[:2] == ['pct', 'config']:
            out = conf.read_text().split('\n[', 1)[0].rstrip('\n') + '\n'
        elif args[:2] == ['cat', '/etc/subuid'] or args[:2] == ['cat', '/etc/subgid']:
            out = (self.tmp / args[1].rsplit('/', 1)[1]).read_text()
        elif args[:2] == ['pct', 'set']:
            main, _, rest = conf.read_text().partition('\n[')
            lines = main.rstrip('\n').split('\n')
            if args[3] == '--delete':
                lines = [x for x in lines if not x.startswith(args[4] + ':')]
            else:
                lines.append(f'{args[3][2:]}: {args[4]}')
            conf.write_text('\n'.join(lines) + '\n' + ('\n[' + rest if rest else ''))
        if kw.get('capture_output'):
            return subprocess.CompletedProcess(args, 0, out, '')
        print(out, end='')
        return subprocess.CompletedProcess(args, 0)

    def ssh(self, host, args, port=22, timeout=75, data=None):
        self.calls.append(args)
        out, err = io.StringIO(), io.StringIO()
        with pytest.MonkeyPatch.context() as m, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            m.setenv('SSH_ORIGINAL_COMMAND', shlex.join(args))
            rc = g.main()
        return ssh.Result(rc, out.getvalue(), err.getvalue())


@pytest.fixture
def pve(client, tmp_path, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_guard='9')
    h = Host(tmp_path, monkeypatch)
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [GUEST], 'error': '', 'guard': 9,
               'host_info': {'subuid': [], 'subgid': []},
               'host_change': {'ids': '9001-9006', 'paths': [str(tmp_path / 'freigabe')]}})
    monkeypatch.setattr(scan, 'start', lambda *a, **k: True)  # kein Neu-Einlesen im Test
    return h


def run(client, form, confirm='9002', **extra):
    return client.post('/aenderung/ausfuehren', data={**form, 'host_id': host_id(), 'confirm': confirm, **extra},
                       follow_redirects=False)


def undo(client, pve):
    e = change.entries()[0]
    r = client.post(f'/aenderungen/{e["id"]}/rueckgaengig')
    assert 'Einstellungen zurückspielen' in r.text and 'host-restore 9002 9002-' in r.text
    r = run(client, {'action': 'conf-zurueck', 'vmid': '9002', **e['undo']['params']}, undo_of=str(e['id']))
    assert r.status_code == 303
    return change.entries()[0]


def test_mount_punkt_hinzu_und_zurueck(client, pve):
    vorher = pve.conf()
    form = {'action': 'mp-hinzu', 'vmid': '9002', 'src': str(pve.tmp / 'freigabe' / 'neu'), 'dst': '/mnt/neu', 'ro': '1'}
    r = client.post('/aenderung/vorschau', data=form)
    assert r.status_code == 200 and f"pct set 9002 --mp1 {pve.tmp}/freigabe/neu,mp=/mnt/neu,ro=1" in r.text
    assert 'Container-Nummer eintippen' in r.text and 'Risiko' in r.text
    assert all(c[0] in ('version', 'pct', 'cat') and c[:2] != ['pct', 'set'] for c in pve.calls)  # Vorschau ändert nichts
    r = run(client, form)
    assert r.status_code == 303
    e = change.entries()[0]
    assert e['result'] == 'ok', e['detail']
    assert f'mp1: {pve.tmp}/freigabe/neu,mp=/mnt/neu,ro=1' in pve.conf() and pve.conf().endswith('\n[vorher]\nhostname: alt\n')
    assert e['undo']['action'] == 'conf-zurueck' and e['backup'].startswith('arch: amd64')
    assert 'Erledigt und nachgeprüft' in client.get(r.headers['location']).text

    z = undo(client, pve)
    assert z['result'] == 'ok' and pve.conf() == vorher and change.entry(e['id'])['undone_by'] == z['id']


def test_mount_punkt_entfernen(client, pve):
    form = {'action': 'mp-weg', 'vmid': '9002', 'key': 'mp0'}
    assert 'pct set 9002 --delete mp0' in client.post('/aenderung/vorschau', data=form).text
    run(client, form)
    assert change.entries()[0]['result'] == 'ok' and 'mp0:' not in pve.conf()
    assert undo(client, pve)['result'] == 'ok' and 'mp0: /srv/ppm-test/share' in pve.conf()


def test_mapping_setzen_und_zurueck(client, pve):
    vorher = pve.conf()
    form = {'action': 'mapping', 'vmid': '9002', 'u': '1000', 'g': '1000'}
    r = client.post('/aenderung/vorschau', data=form)
    assert 'host-subid subuid 1000' in r.text and 'host-idmap 9002 u:0:100000:1000 u:1000:1000:1' in r.text
    assert 'lxc.idmap: g 1001 101001 64535' in r.text
    assert 'name="ack"' in r.text and 'pct mount 9002' in r.text  # Dateien nachziehen: Befehl zum Kopieren
    vorher_n = len(change.entries())
    assert 'Bitte bestätigen' in run(client, form).text and len(change.entries()) == vorher_n  # ohne Häkchen nicht
    run(client, form, ack='1')
    e = change.entries()[0]
    assert e['result'] == 'ok', e['detail']
    assert 'lxc.idmap: u 1000 1000 1' in pve.conf() and 'root:1000:1' in (pve.tmp / 'subgid').read_text()
    assert undo(client, pve)['result'] == 'ok' and pve.conf() == vorher
    assert 'root:1000:1' in (pve.tmp / 'subuid').read_text()  # bleibt stehen (harmlos)


def test_nur_gestoppt(client, pve):
    pve.status = 'running'
    form = {'action': 'mp-weg', 'vmid': '9002', 'key': 'mp0'}
    r = client.post('/aenderung/vorschau', data=form)
    assert 'läuft' in r.text and 'name="confirm"' not in r.text
    vorher = len(change.entries())
    run(client, form)
    assert len(change.entries()) == vorher and 'mp0:' in pve.conf()


def test_waechter_lehnt_laufenden_container_ab(client, pve, monkeypatch):
    """Läuft der Container erst nach der Vorschau an, lehnt der Wächter selbst ab."""
    p = hostchange.plan('mp-weg', scan.latest(), 9002, {'key': 'mp0'}, hostchange.live('h', 22, 9002))
    pve.status = 'running'
    hostchange.execute(p, 'h', 22)
    e = change.entries()[0]
    assert e['result'] == 'fehler' and 'läuft' in e['detail'] and not e['undo'] and 'mp0:' in pve.conf()


def test_nicht_freigegeben(client, pve):
    (pve.tmp / 'host-aendern-erlaubt').write_text('9003\n')
    form = {'action': 'mp-weg', 'vmid': '9002', 'key': 'mp0'}
    assert 'host-aendern-erlaubt' in client.post('/aenderung/vorschau', data=form).text
    vorher = len(change.entries())
    assert 'nicht freigegeben' in run(client, form).text and len(change.entries()) == vorher


def test_alter_waechter(client, pve, monkeypatch):
    monkeypatch.setattr(g, 'VERSION', '8')
    r = client.post('/aenderung/vorschau', data={'action': 'mp-weg', 'vmid': '9002', 'key': 'mp0'})
    assert 'Version 9' in r.text and 'name="confirm"' not in r.text


@pytest.mark.parametrize('params, fehler', [
    ({'src': '/etc', 'dst': '/mnt/etc'}, 'Einhängen darf PermLens nur Ordner'),
    ({'src': '/srv/a,mp=/x', 'dst': '/y'}, 'ungültig'),
    ({'src': '/srv/a b', 'dst': '/y'}, 'ungültig'),
    ({'src': '/srv/ppm-test/share', 'dst': '/mnt/share'}, 'schon ein Einhängepunkt'),
    ({'src': '/srv/ppm-test/share', 'dst': '/x', 'key': 'mp0'}, 'schon belegt'),
])
def test_mount_punkt_fehler(params, fehler, pve):
    p = hostchange.plan('mp-hinzu', scan.latest(), 9002, params, hostchange.live('h', 22, 9002))
    assert fehler in p['error'][0] and not p['cmd']


def test_mount_punkt_schon_eingehaengter_ordner(pve):
    """Ordner, die schon in einem Container hängen (hier 9002 selbst), sind erlaubt."""
    p = hostchange.plan('mp-hinzu', scan.latest(), 9002, {'src': '/srv/ppm-test/share', 'dst': '/mnt/zwei'},
                        hostchange.live('h', 22, 9002))
    assert p['error'] is None and p['cmd'] == [['pct', 'set', '9002', '--mp1', '/srv/ppm-test/share,mp=/mnt/zwei']]
    assert ('Der Ordner gehört auf dem Host §:§, im Container §.', 1000, 1000, 'nobody:nogroup') in p['after']


def test_mapping_dateien_nachziehen_bleibt_von_hand(pve):
    lv = hostchange.live('h', 22, 9002)
    last = {**scan.latest(), 'guests': [{**GUEST, 'details': {'users': [{'name': 'alice', 'uid': 1000, 'gid': 1000}],
                                                                  'groups': []}}]}
    p = hostchange.plan('mapping', last, 9002, {'u': '1000', 'g': ''}, lv)
    assert p['error'] is None and p['need_ack'] and 'chown -h 1000' in p['fix']
    assert ('Benutzer § (§): heute § auf dem Host', 1000, 'alice', 101000) in p['moved']
    assert not any('find' in a or 'chown' in a for c in p['cmd'] for a in c)  # nie über den Wächter


def test_mapping_fehler(pve):
    lv = hostchange.live('h', 22, 9002)
    assert 'Nummern von 1 bis 65533' in hostchange.plan('mapping', scan.latest(), 9002, {'u': '0'}, lv)['error'][0]
    assert 'ändert sich nichts' in hostchange.plan('mapping', scan.latest(), 9002, {'u': '', 'g': ''}, lv)['error'][0]
    lv3 = hostchange.live('h', 22, 9003)
    assert 'privilegiert' in hostchange.plan('mapping', scan.latest(), 9003, {'u': '1000'}, lv3)['error'][0]


def test_zurueck_nach_fremder_aenderung_abgelehnt(client, pve):
    run(client, {'action': 'mp-weg', 'vmid': '9002', 'key': 'mp0'})
    e = change.entries()[0]
    p = pve.tmp / 'lxc' / '9002.conf'
    p.write_text(p.read_text().replace('hostname: ppm-test-share', 'hostname: umbenannt', 1))
    run(client, {'action': 'conf-zurueck', 'vmid': '9002', **e['undo']['params']}, undo_of=str(e['id']))
    z = change.entries()[0]
    assert z['result'] == 'fehler' and 'verändert' in z['detail'] and 'hostname: umbenannt' in pve.conf()


def test_container_seite_zeigt_aktionen(client, pve):
    r = client.get('/container/9002?tab=host')
    assert 'Mount-Punkt hinzufügen …' in r.text and 'Entfernen …' in r.text and 'Mapping ändern …' in r.text
    set_pve(pve_guard='8')
    r = client.get('/container/9002?tab=host')
    assert 'Mount-Punkt hinzufügen …' not in r.text and 'Version 9' in r.text


def test_mapping_assistent_zeigt_ausfuehren(client, pve):
    r = client.get('/mapping?art=bestehend&ct=9002')
    assert 'Von PermLens ausführen lassen' in r.text and 'value="mapping"' in r.text
