"""Wächter-Script Version 8: Docker im Container und „Nachschauen“-Konsole (nur lesen)."""
import json
import subprocess
from pathlib import Path

import pytest

from test_waechter import g

INSPECT = (Path(__file__).parent / 'fixtures' / 'docker-inspect.json').read_text()


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    (tmp_path / '9006.conf').write_text('mp0: /srv/ppm-test/share,mp=/mnt/share\n')
    (tmp_path / '112.conf').write_text('mp0: /mnt/appdata,mp=/data\n')
    monkeypatch.setattr(g, 'CONF_DIR', str(tmp_path))
    f = tmp_path / 'schreiben-erlaubt'
    f.write_text('9001-9006\n')
    monkeypatch.setattr(g, 'WRITE_FILE', str(f))


def ct(*cmd, vmid='9006'):
    return ['pct', 'exec', vmid, '--', *cmd]


def test_version_8():
    assert int(g.VERSION) >= 8


# ---- Konsole
KONSOLE = [
    ct('id', 'alice'), ct('id', '1000'),
    ct('getent', 'passwd', 'alice'), ct('getent', 'group', '2000'),
    ct('ls', '-lnd', '/mnt/share'), ct('ls', '-lnd', '/etc/passwd'),
    ct('df', '-hP', '/mnt/share'), ct('df', '-hP', '/home/alice'),
    ct('ls', '-lnd', '/data', vmid='112'),                       # nur der Eintrag: auch ohne Freigabe
]

KONSOLE_NEIN = [
    ct('id'), ct('id', '-u', 'alice'), ct('id', 'al;ice'),
    ct('getent', 'shadow', 'alice'), ct('getent', 'passwd', 'a', 'b'),
    ct('ls', '-la', '/mnt/share'), ct('ls', '-lnd', '/mnt/share', '/etc'), ct('ls', '-lndR', '/mnt/share'),
    ct('ls', '-lnd', '/mnt/../etc'), ct('ls', '-lnd', 'relativ'),
    ct('df', '-hP', '/etc'), ct('df', '-h', '/mnt/share'), ct('df', '-hP'),
    ct('ls', '-ln', '/data', vmid='112'),                        # Dateinamen: Container nicht freigegeben
    ct('cat', '/etc/shadow'), ct('sh', '-c', 'ls'), ct('docker', 'ps'),
]


@pytest.mark.parametrize('args', KONSOLE)
def test_konsole_erlaubt(args):
    assert g.check(args) is True


@pytest.mark.parametrize('args', KONSOLE_NEIN)
def test_konsole_abgelehnt(args):
    assert not g.check(args)


def test_dateinamen_nur_freigegeben():
    assert g.check(ct('ls', '-ln', '/mnt/share')) == 'list'
    assert g.check(ct('ls', '-ln', '/data', vmid='112')) is False


@pytest.mark.parametrize('pfad,grund', [('/etc', 'Nur in eingehängten Ordnern'), ('/mnt', 'Nur in eingehängten Ordnern')])
def test_dateinamen_nur_in_eingehaengten_ordnern(pfad, grund):
    assert grund in g.precheck(ct('ls', '-ln', pfad))


def test_dateinamen_ohne_symlink(monkeypatch):
    monkeypatch.setattr(g.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '/etc\n', ''))
    assert 'symbolische Verknüpfung' in g.precheck(ct('ls', '-ln', '/mnt/share/link'))
    monkeypatch.setattr(g.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '/mnt/share/fotos\n', ''))
    assert g.precheck(ct('ls', '-ln', '/mnt/share/fotos')) == ''


def test_dateinamen_meldung(monkeypatch, capsys):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'pct exec 112 -- ls -ln /data')
    monkeypatch.setattr(g, 'log', lambda t: None)
    assert g.main() == 126
    assert 'Dateinamen zeigt PermLens nur in freigegebenen Containern' in capsys.readouterr().err


# ---- Docker: welche Befehlsformen
DOCKER = [
    ['docker-ps', '9006'], ['docker-ps', '112'],                 # lesen: auch ohne Freigabe
    ['docker-inspect', '9006', 'paperless'], ['docker-top', '9006', 'paperless-ngx_web.1'],
    ['docker-id', '9006', 'immich_server'],
    ['docker-stat', '9006', 'paperless', '/usr/src/paperless/media'],
]

DOCKER_NEIN = [
    ['docker-ps'], ['docker-ps', '9006', '-a'], ['docker-ps', 'abc'],
    ['docker-inspect', '9006'], ['docker-inspect', '9006', '-f', '{{.Config.Env}}'],
    ['docker-inspect', '9006', '--format={{json .}}'], ['docker-inspect', '9006', 'a;b'],
    ['docker-inspect', '9006', 'paperless', 'immich'], ['docker-top', '9006', '-x'],
    ['docker-id', '9006', 'paperless', 'sh'], ['docker-exec', '9006', 'paperless', 'id'],
    ['docker-stat', '9006', 'paperless'], ['docker-stat', '9006', 'paperless', '../etc'],
    ['docker', 'ps'], ct('docker', 'inspect', 'paperless'), ct('docker', 'exec', 'paperless', 'sh'),
]


@pytest.mark.parametrize('args', DOCKER)
def test_docker_erlaubt(args):
    assert g.check(args) == 'docker'


@pytest.mark.parametrize('args', DOCKER_NEIN)
def test_docker_abgelehnt(args):
    assert not g.check(args)


# ---- Docker: was herauskommt
class Docker:
    """Ersetzt pct exec … docker …: merkt sich die Aufrufe und liefert vorbereitete Antworten."""
    def __init__(self, monkeypatch, antworten):
        self.calls, self.antworten = [], antworten
        monkeypatch.setattr(g, 'in_ct', self)
        monkeypatch.setattr(g, 'log', lambda t: None)

    def __call__(self, vmid, cmd):
        self.calls.append((vmid, cmd))
        for key, value in self.antworten.items():
            if cmd[:len(key)] == list(key):
                return value
        return 1, '', 'unerwartet'


def lauf(capsys, args):
    rc = g.docker_builtin(args)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_inspect_gibt_nur_ausgewaehlte_felder(monkeypatch, capsys):
    d = Docker(monkeypatch, {('docker', 'inspect'): (0, INSPECT, '')})
    rc, out, _ = lauf(capsys, ['docker-inspect', '9006', 'paperless'])
    assert rc == 0
    assert d.calls == [('9006', ['docker', 'inspect', '--type', 'container', '--', 'paperless'])]
    app = json.loads(out)
    assert app['name'] == 'paperless' and app['user'] == '1000:1000' and app['state'] == 'running'
    assert app['env'] == {'PUID': '1000', 'PGID': '1000', 'UMASK': '022', 'USERMAP_UID': '1000'}
    assert app['labels'] == {'com.docker.compose.project': 'probe'}
    assert {'type': 'bind', 'source': '/mnt/share', 'destination': '/usr/src/paperless/media', 'rw': True} in app['mounts']
    # Geheimnisse und Befehlszeilen verlassen den Wächter nie
    for wort in ('geheim', 'SECRET', 'PATH=', 'sleep', 'Cmd', 'abc'):
        assert wort not in out


def test_inspect_unbekannte_app(monkeypatch, capsys):
    Docker(monkeypatch, {('docker', 'inspect'): (1, '[]', 'Error: No such container: x\n')})
    rc, out, _ = lauf(capsys, ['docker-inspect', '9006', 'x'])
    assert rc == 1 and json.loads(out) == {'docker': True, 'error': 'Error: No such container: x'}


def test_ps(monkeypatch, capsys):
    zeilen = 'paperless\tghcr.io/paperless-ngx/paperless-ngx:2\trunning\tUp 3 hours\nredis\tredis:7\texited\tExited (0) 2 days ago\n'
    d = Docker(monkeypatch, {('docker', 'ps'): (0, zeilen, '')})
    rc, out, _ = lauf(capsys, ['docker-ps', '9006'])
    assert rc == 0 and d.calls[0][1] == ['docker', 'ps', '-a', '--no-trunc', '--format', g.PS_FORMAT]
    assert json.loads(out) == {'docker': True, 'apps': [
        {'name': 'paperless', 'image': 'ghcr.io/paperless-ngx/paperless-ngx:2', 'state': 'running', 'status': 'Up 3 hours'},
        {'name': 'redis', 'image': 'redis:7', 'state': 'exited', 'status': 'Exited (0) 2 days ago'}]}


def test_ps_ohne_docker(monkeypatch, capsys):
    Docker(monkeypatch, {('docker', 'ps'): (255, '', 'lxc-attach: 9001: Failed to exec "docker"\n')})
    rc, out, _ = lauf(capsys, ['docker-ps', '9001'])
    assert rc == 0 and json.loads(out)['docker'] is False


def test_ps_daemon_aus(monkeypatch, capsys):
    Docker(monkeypatch, {('docker', 'ps'): (1, '', 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\n')})
    rc, out, _ = lauf(capsys, ['docker-ps', '9006'])
    assert rc == 1 and json.loads(out)['docker'] is True and 'Cannot connect' in json.loads(out)['error']


def test_top_ohne_befehlszeile(monkeypatch, capsys):
    ps = 'PID UID GID COMMAND\n4242 0 0 s6-svscan\n4300 1000 1000 gunicorn\n'
    d = Docker(monkeypatch, {('docker', 'top'): (0, ps, '')})
    rc, out, _ = lauf(capsys, ['docker-top', '9006', 'paperless'])
    assert d.calls[0][1] == ['docker', 'top', 'paperless', '-eo', 'pid,uid,gid,comm']
    assert json.loads(out) == {'processes': [{'uid': 0, 'gid': 0, 'comm': 's6-svscan'},
                                             {'uid': 1000, 'gid': 1000, 'comm': 'gunicorn'}]}


def test_id(monkeypatch, capsys):
    Docker(monkeypatch, {('docker', 'exec'): (0, 'uid=1000(paperless) gid=1000(paperless) groups=1000(paperless)\n', '')})
    rc, out, _ = lauf(capsys, ['docker-id', '9006', 'paperless'])
    assert rc == 0 and json.loads(out) == {'id': 'uid=1000(paperless) gid=1000(paperless) groups=1000(paperless)'}


def test_stat_nur_eingehaengte_ziele(monkeypatch, capsys):
    d = Docker(monkeypatch, {('docker', 'inspect'): (0, INSPECT, ''),
                             ('docker', 'exec'): (0, 'drwxrwsr-x|2775|1000|1000|?|?|directory|/usr/src/paperless/media\n', '')})
    rc, out, _ = lauf(capsys, ['docker-stat', '9006', 'paperless', '/usr/src/paperless/media'])
    assert rc == 0 and out.endswith('/usr/src/paperless/media\n')
    assert d.calls[-1][1] == ['docker', 'exec', 'paperless', 'stat', '-c', g.STAT_FORMAT, '--', '/usr/src/paperless/media']
    rc, out, err = lauf(capsys, ['docker-stat', '9006', 'paperless', '/etc/shadow'])
    assert rc == 126 and 'Nur eingehängte Ordner der App' in err
    assert len([c for c in d.calls if c[1][:2] == ['docker', 'exec']]) == 1


def test_stat_abgelehnt_nur_einmal_im_protokoll(monkeypatch, capsys):
    Docker(monkeypatch, {('docker', 'inspect'): (0, INSPECT, '')})
    zeilen = []
    monkeypatch.setattr(g, 'log', zeilen.append)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'docker-stat 9006 paperless /etc/shadow')
    assert g.main() == 126
    assert zeilen == ['ABGELEHNT: docker-stat 9006 paperless /etc/shadow – Pfad ist kein eingehängtes Ziel der App']
