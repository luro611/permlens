"""„Nachschauen“-Konsole (AP 6.3): nur feste, lesende Befehle, übersetzt in genau eine Form des Wächters."""
import json

import pytest

from app import db
from app.pve import console, scan, ssh
from conftest import set_pve  # noqa: E402
from test_waechter import g as guard

FMT = scan.STAT[2]


# ---------------------------------------------------------------- Übersetzung
@pytest.mark.parametrize('kind, text, erwartet', [
    ('host', 'pct list', ['pct', 'list']),
    ('host', 'pct config 9006', ['pct', 'config', '9006']),
    ('host', 'cat /etc/subuid', ['cat', '/etc/subuid']),
    ('host', 'getent group', ['getent', 'group']),
    ('host', 'stat /srv/ppm-test/share', ['stat', '-c', FMT, '/srv/ppm-test/share']),
    ('host', 'getfacl /srv/ppm-test/share', ['acl', '/srv/ppm-test/share']),
    ('host', 'findmnt', scan.FINDMNT),
    ('lxc', 'id alice', ['pct', 'exec', '9006', '--', 'id', 'alice']),
    ('lxc', 'getent passwd alice', ['pct', 'exec', '9006', '--', 'getent', 'passwd', 'alice']),
    ('lxc', 'ls -ld /mnt/share', ['pct', 'exec', '9006', '--', 'ls', '-lnd', '/mnt/share']),
    ('lxc', 'ls -la /mnt/share', ['pct', 'exec', '9006', '--', 'ls', '-ln', '/mnt/share']),
    ('lxc', 'ls /mnt/share', ['pct', 'exec', '9006', '--', 'ls', '-ln', '/mnt/share']),
    ('lxc', 'df -h /mnt/share', ['pct', 'exec', '9006', '--', 'df', '-hP', '/mnt/share']),
    ('lxc', 'getfacl /mnt/share', ['pct', 'exec', '9006', '--', 'getfacl', '-cpn', '/mnt/share']),
    ('lxc', 'stat /mnt/share /home', ['pct', 'exec', '9006', '--', 'stat', '-c', FMT, '/mnt/share', '/home']),
    ('lxc', 'docker ps', ['docker-ps', '9006']),
    ('app', 'id', ['docker-id', '9006', 'paperless']),
    ('app', 'ps', ['docker-top', '9006', 'paperless']),
    ('app', 'inspect', ['docker-inspect', '9006', 'paperless']),
    ('app', 'stat /data', ['docker-stat', '9006', 'paperless', '/data']),
])
def test_uebersetzung(kind, text, erwartet):
    args, view = console.translate(kind, 9006, 'paperless', text)
    assert args == erwartet, view


@pytest.mark.parametrize('kind, text, antwort', [
    ('lxc', 'bash', 'Eine Shell gibt es in PermLens nicht'),
    ('lxc', 'cat /etc/shadow', 'Dateiinhalte zeigt PermLens nicht'),
    ('lxc', 'rm -rf /mnt/share', 'Die Konsole liest nur'),
    ('lxc', 'chmod 777 /mnt/share', 'Die Konsole liest nur'),
    ('app', 'sh', 'Eine Shell gibt es'),
    ('lxc', 'docker exec paperless sh', 'Dockhand'),
    ('lxc', 'ls /mnt/share; id', '„§“ gibt es hier nicht'),           # ; ist kein Trenner, ganzer Pfad ungültig
    ('lxc', 'ls -lR /mnt/share', '„§“ gibt es hier nicht'),
    ('lxc', 'stat /mnt/../etc', '„§“ gibt es hier nicht'),
    ('lxc', 'id $(whoami)', '„§“ gibt es hier nicht'),
    ('host', 'id root', '„§“ gibt es hier nicht'),                     # auf dem Host nichts Neues
    ('host', 'cat /etc/pve/priv/authkey.key', 'Dateiinhalte'),
    ('host', 'ls /root', '„§“ gibt es hier nicht'),
    ('app', 'stat /etc/passwd /data;x', '„§“ gibt es hier nicht'),
    ('lxc', 'ls "/mnt/sh', 'nicht lesbar'),
])
def test_nicht_erlaubt(kind, text, antwort):
    args, view = console.translate(kind, 9006, 'paperless', text)
    assert args is None and antwort in view[0]


def test_hilfe():
    assert console.translate('lxc', 9006, '', 'hilfe') == (None, 'hilfe')
    assert console.translate('lxc', 9006, '', '   ') == (None, None)


@pytest.mark.parametrize('kind', ['host', 'lxc', 'app'])
def test_jeder_uebersetzte_befehl_ist_im_waechter_erlaubt(kind, tmp_path, monkeypatch):
    """Was die Konsole an den Wächter schickt, muss dort eine erlaubte Form sein (sonst sinnlose Fehler)."""
    (tmp_path / '9006.conf').write_text('mp0: /srv/ppm-test/share,mp=/mnt/share\n')
    monkeypatch.setattr(guard, 'CONF_DIR', str(tmp_path))
    f = tmp_path / 'schreiben-erlaubt'
    f.write_text('9006\n')
    monkeypatch.setattr(guard, 'WRITE_FILE', str(f))
    examples = {'host': ['pct list', 'pct config 9006', 'cat /etc/subgid', 'findmnt', 'getent passwd',
                         'stat /srv/ppm-test/share', 'getfacl /srv/ppm-test/share'],
                'lxc': ['id alice', 'getent group media', 'ls -ld /etc', 'ls -l /mnt/share', 'stat /mnt/share',
                        'getfacl /mnt/share', 'df -h /mnt/share', 'findmnt', 'docker ps', 'cat /etc/exports', 'testparm -s'],
                'app': ['id', 'ps', 'inspect', 'stat /data']}[kind]
    for text in examples:
        args, _ = console.translate(kind, 9006, 'paperless', text)
        assert args and guard.check(args), text


# ---------------------------------------------------------------- Ausgabe
def test_ausgabe_stat_und_acl(monkeypatch):
    out = {'stat': 'drwxrwsr-x|2775|1000|2000|alice|UNKNOWN|directory|/mnt/share\n',
           'acl': json.dumps({'path': '/x', 'access': [{'tag': 'user_obj', 'id': None, 'perm': 'rwx'},
                                                       {'tag': 'group', 'id': 2000, 'perm': 'rwx'}], 'default': []})}
    monkeypatch.setattr(ssh, 'run', lambda h, args, p=22, timeout=None: ssh.Result(0, out['acl' if args[0] == 'acl' else 'stat'], ''))
    r = console.run('h', 22, 'lxc', 9006, '', 'stat /mnt/share')
    assert r['out'] == 'drwxrwsr-x  2775  1000:2000 (alice:–)  directory  /mnt/share'
    r = console.run('h', 22, 'host', None, '', 'getfacl /x')
    assert r['out'] == '# file: /x\nuser::rwx\ngroup:2000:rwx'


def test_alter_waechter(monkeypatch):
    monkeypatch.setattr(ssh, 'run', lambda *a, **k: ssh.Result(126, '', 'permlens-guard: Befehl nicht erlaubt\n'))
    r = console.run('h', 22, 'lxc', 9006, '', 'id alice')
    assert 'Version 8' in r['error'][0]


def test_dateinamen_nicht_freigegeben(monkeypatch):
    msg = 'permlens-guard: Dateinamen zeigt PermLens nur in freigegebenen Containern (/etc/permlens/schreiben-erlaubt)\n'
    monkeypatch.setattr(ssh, 'run', lambda *a, **k: ssh.Result(126, '', msg))
    r = console.run('h', 22, 'lxc', 112, '', 'ls -l /data')
    assert r['error'][0].startswith('Wächter: Dateinamen zeigt PermLens nur')


# ---------------------------------------------------------------- Seite
GUEST = {'vmid': 9006, 'name': 'ppm-test-tool', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': True, 'mounts': []},
         'details': {'users': [], 'groups': [], 'stat': {},
                     'docker': {'apps': [{'name': 'paperless', 'state': 'running', 'mounts': []}], 'error': ''}}}


@pytest.fixture
def pve(client, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_guard='8')
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [GUEST], 'error': ''})
    calls = []

    def run(host, args, port=22, timeout=None, data=None):
        calls.append(args)
        return ssh.Result(0, 'uid=1000(alice) gid=1000(alice) groups=1000(alice)\n', '')
    monkeypatch.setattr(ssh, 'run', run)
    return calls


def test_seite_und_ziele(client, pve):
    r = client.get('/konsole?ziel=9006')
    assert r.status_code == 200 and '9006$' in r.text and 'value="9006:paperless"' in r.text
    assert 'data-cmd="id &lt;Name&gt;"' in r.text


def test_ausfuehren_und_protokoll(client, pve):
    r = client.post('/konsole', data={'ziel': '9006', 'eingabe': 'id alice'})
    assert 'uid=1000(alice)' in r.text and pve == [['pct', 'exec', '9006', '--', 'id', 'alice']]
    e = next(e for e in db.audit_entries() if e['action'] == 'konsole')
    assert e['target'] == '9006' and json.loads(e['details']) == {'befehl': 'pct exec 9006 -- id alice'}
    assert 'uid=1000' not in (e['details'] or '')                                   # nie die Ausgabe
    assert 'Zuletzt nachgeschaut' in client.get('/konsole').text


def test_nicht_erlaubt_geht_nicht_zum_waechter(client, pve):
    before = len(db.audit_entries())
    r = client.post('/konsole', data={'ziel': '9006', 'eingabe': 'bash'})
    assert 'Eine Shell gibt es in PermLens nicht' in r.text and pve == []
    assert len(db.audit_entries()) == before


def test_fremde_herkunft(client, pve):
    r = client.post('/konsole', data={'ziel': '9006', 'eingabe': 'id alice'}, headers={'Origin': 'http://evil.example'},
                    follow_redirects=False)
    assert r.status_code == 303 and pve == []


def test_unbekanntes_ziel(client, pve):
    r = client.post('/konsole', data={'ziel': '112', 'eingabe': 'id alice'})
    assert r.status_code == 200 and pve == []
