"""Wächter-Script Version 7: UID/GID ändern, umnummerieren, rekursiv, Sicherung und Wiederherstellen."""
import io
import subprocess

import pytest

from test_waechter import g


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    (tmp_path / '9005.conf').write_text('mp1: /srv/ppm-test/share,mp=/mnt/share\n')
    monkeypatch.setattr(g, 'CONF_DIR', str(tmp_path))
    f = tmp_path / 'schreiben-erlaubt'
    f.write_text('9001-9006\n')
    monkeypatch.setattr(g, 'WRITE_FILE', str(f))


def ct(*cmd, vmid='9005'):
    return ['pct', 'exec', vmid, '--', *cmd]


ERLAUBT = [
    ct('usermod', '-u', '1010', 'bob'),
    ct('groupmod', '-g', '2010', 'media'),
    ct('chown', '-R', '-h', '1000:2000', '/mnt/share/fotos'),
    ct('chmod', '-R', 'g+rwX,o-rwx', '/mnt/share'),
    ct('chmod', '-R', '2775', '/mnt/share'),
    ct('setfacl', '-R', '-m', 'g:2000:rwX'.replace('X', 'x'), '/mnt/share'),
    ct('setfacl', '-R', '-d', '-m', 'g:2000:rwx', '/mnt/share'),
    ct('setfacl', '-R', '-x', 'u:1001', '/mnt/share'),
    ct('getfacl', '-R', '-p', '-n', '-P', '/mnt/share'),
    ct('find', '/mnt/share', '-xdev', '-printf', '.'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-printf', '.'),
    ct('find', '/mnt/share', '-xdev', '-group', '2000', '-printf', '.'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-exec', 'chown', '-h', '1010', '{}', '+'),
    ct('find', '/mnt/share', '-xdev', '-group', '2000', '-exec', 'chgrp', '-h', '2010', '{}', '+'),
    ct('permlens-restore', '/mnt/share'),
]

ABGELEHNT = [
    ct('usermod', '-u', '0', 'bob'),
    ct('usermod', '-u', '1010', '-o', 'bob'),
    ct('groupmod', '-g', '999', 'media'),
    ct('chown', '-R', '1000:2000', '/mnt/share'),                 # ohne -h
    ct('chown', '-R', '-h', '-L', '1000:2000', '/mnt/share'),
    ct('chmod', '-R', 'u+s', '/mnt/share'),                       # setuid nie
    ct('chmod', '-R', 'a+s', '/mnt/share'),
    ct('chmod', '-R', 'g+s', '/mnt/share'),
    ct('chmod', '-R', '4755', '/mnt/share'),
    ct('chmod', '-R', 'g=rwx', '/mnt/share'),
    ct('setfacl', '-R', '-b', '/mnt/share'),
    ct('setfacl', '-R', '-d', '-x', 'u:1001', '/mnt/share'),
    ct('getfacl', '-R', '/mnt/share'),
    ct('find', '/mnt/share', '-printf', '%p\n'),                  # nur Punkte, keine Namen
    ct('find', '/mnt/share', '-xdev', '-printf', '%p'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-delete'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-exec', 'rm', '-h', '1010', '{}', '+'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-exec', 'chown', '1010', '{}', '+'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-exec', 'chown', '-h', '1010', '{}', ';'),
    ct('find', '/mnt/share', '-user', '1001', '-exec', 'chown', '-h', '1010', '{}', '+'),
    ct('find', '/mnt/share', '-xdev', '-user', '1001', '-exec', 'chgrp', '-h', '1010', '{}', '+'),
    ct('permlens-restore', '/mnt/share', '/etc'),
    ct('chmod', '-R', 'g+w', '/mnt/share', vmid='112'),
]


@pytest.mark.parametrize('args', ERLAUBT)
def test_erlaubt(args):
    assert g.check(args) == 'write'


@pytest.mark.parametrize('args', ABGELEHNT)
def test_abgelehnt(args):
    assert g.check(args) != 'write'


@pytest.mark.parametrize('args', [ct('chown', '-R', '-h', '0:0', '/etc'), ct('find', '/', '-xdev', '-printf', '.'),
                                  ct('getfacl', '-R', '-p', '-n', '-P', '/etc'), ct('permlens-restore', '/etc')])
def test_nur_in_eingehaengten_ordnern(args):
    assert g.check(args) == 'write' and not g.inside_targets(args[2], g.write_path(args[4:]))


BACKUP = ('# file: /mnt/share\n# owner: 1000\n# group: 2000\n# flags: -s-\nuser::rwx\ngroup::rwx\nother::r-x\n\n'
          '# file: /mnt/share/a\\040b\n# owner: 1000\n# group: 2000\nuser::rw-\ngroup::rw-\nother::---\n\n')


class Lauf:
    def __init__(self):
        self.calls, self.inputs = [], []

    def __call__(self, args, **kw):
        self.calls.append(args)
        self.inputs.append(kw.get('input'))
        out = '/mnt/share\n' if 'realpath' in args else ''
        return subprocess.CompletedProcess(args, 0, out, '')


def restore(monkeypatch, text):
    lauf = Lauf()
    monkeypatch.setattr(g.subprocess, 'run', lauf)
    monkeypatch.setattr(g.sys, 'stdin', io.TextIOWrapper(io.BytesIO(text.encode())))
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'pct exec 9005 -- permlens-restore /mnt/share')
    return g.main(), lauf


def test_wiederherstellen(monkeypatch):
    rc, lauf = restore(monkeypatch, BACKUP)
    assert rc == 0
    assert lauf.calls[-1] == ['pct', 'exec', '9005', '--', 'setfacl', '--physical', '--restore=-']
    assert lauf.inputs[-1] == BACKUP.encode()


@pytest.mark.parametrize('text', [
    BACKUP + '# file: /etc/shadow\n# owner: 1000\n# group: 1000\nuser::rw-\n',
    BACKUP + '# file: /mnt/sharex\n# owner: 0\n',
    BACKUP + '# file: /mnt/share/../../etc\n# owner: 0\n',
    BACKUP + '# file: /mnt/share/\\057..\\057..\\057etc\n# owner: 0\n',   # versteckt per Oktal-Schreibweise
    BACKUP.replace('# flags: -s-', '# flags: s--'),                     # setuid
    '',
])
def test_wiederherstellen_lehnt_ab(monkeypatch, text):
    rc, lauf = restore(monkeypatch, text)
    assert rc == 126 and not any('--restore=-' in c for c in lauf.calls)


def test_symbolische_rechte():
    assert g.chmod_r_ok('g+rwX,o-rwx') and g.chmod_r_ok('00755') and not g.chmod_r_ok('g+s')
    assert not g.chmod_r_ok('u+s') and not g.chmod_r_ok('+x') and not g.chmod_r_ok('g+rwX,' * 7 + 'o-w')


def test_version_mindestens_7():
    assert int(g.VERSION) >= 7
