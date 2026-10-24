"""Wächter-Script Version 6: Benutzer anlegen und löschen, Mitgliedschaften, Hauptgruppe – nur ab Nummer 1000."""
import subprocess

import pytest

from test_waechter import g


@pytest.fixture(autouse=True)
def schalter(tmp_path, monkeypatch):
    f = tmp_path / 'schreiben-erlaubt'
    f.write_text('9001-9006\n')
    monkeypatch.setattr(g, 'WRITE_FILE', str(f))


def ct(*cmd, vmid='9003'):
    return ['pct', 'exec', vmid, '--', *cmd]


ERLAUBT = [
    ct('useradd', '-m', '-u', '1003', '-g', '2000', 'dave'),
    ct('userdel', 'dave'),
    ct('usermod', '-aG', 'media', 'bob'),
    ct('usermod', '-g', '2000', 'bob'),
    ct('gpasswd', '-d', 'bob', 'media'),
]

ABGELEHNT = [
    ct('useradd', '-m', '-u', '0', '-g', '0', 'dave'),          # root-Nummer
    ct('useradd', '-m', '-u', '999', '-g', '2000', 'dave'),
    ct('useradd', '-m', '-u', '1003', '-g', '2000', '-o', 'dave'),
    ct('useradd', '-u', '1003', '-g', '2000', 'dave'),           # ohne -m
    ct('useradd', '-m', '-u', '1003', '-g', '2000', '-s', '/bin/bash', 'dave'),
    ct('useradd', '-m', '-u', '1003', '-g', '2000', 'Dave'),
    ct('userdel', '-r', 'dave'),                                 # Home bleibt immer
    ct('userdel', '-f', 'dave'),
    ct('usermod', '-aG', 'media,sudo', 'bob'),                   # nur eine Gruppe
    ct('usermod', '-G', 'media', 'bob'),                         # ersetzt alle Gruppen
    ct('usermod', '-g', '0', 'bob'),
    ct('usermod', '-L', 'bob'),
    ct('gpasswd', '-a', 'bob', 'media'),
    ct('gpasswd', 'media'),                                      # Passwort der Gruppe
    ct('passwd', 'bob'),
    ct('chpasswd'),
    ct('useradd', '-m', '-u', '1003', '-g', '2000', 'dave', vmid='112'),  # nicht freigegeben
]


@pytest.mark.parametrize('args', ERLAUBT)
def test_erlaubt(args):
    assert g.check(args) == 'write'


@pytest.mark.parametrize('args', ABGELEHNT)
def test_abgelehnt(args):
    assert g.check(args) != 'write'


class Container:
    """Ersatz für subprocess.run mit einer kleinen passwd/group-Datenbank."""
    def __init__(self):
        self.passwd = {'root': 0, 'bob': 1001, 'sshd': 991}
        self.group = {'root': 0, 'sudo': 27, 'media': 2000}
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append(args)
        if 'getent' in args:
            db, key = args[-2], args[-1]
            table = self.passwd if db == 'passwd' else self.group
            if key in table:
                return subprocess.CompletedProcess(args, 0, f'{key}:x:{table[key]}:\n', '')
            return subprocess.CompletedProcess(args, 2, '', '')
        return subprocess.CompletedProcess(args, 0, '', '')


def run(monkeypatch, cmd):
    c = Container()
    monkeypatch.setattr(g.subprocess, 'run', c)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', ' '.join(cmd))
    return g.main(), c.calls


def test_mitglied_wird_geprueft_und_ausgefuehrt(monkeypatch):
    cmd = ct('usermod', '-aG', 'media', 'bob')
    rc, calls = run(monkeypatch, cmd)
    assert rc == 0 and calls[-1] == cmd
    assert ct('getent', 'passwd', 'bob') in calls and ct('getent', 'group', 'media') in calls


@pytest.mark.parametrize('cmd', [
    ct('usermod', '-aG', 'sudo', 'bob'),        # Systemgruppe: nie
    ct('usermod', '-aG', 'root', 'bob'),
    ct('usermod', '-aG', 'media', 'sshd'),      # Systembenutzer
    ct('usermod', '-aG', 'media', 'root'),
    ct('gpasswd', '-d', 'bob', 'sudo'),
    ct('userdel', 'root'),
    ct('userdel', 'sshd'),
    ct('userdel', 'gibtsnicht'),
    ct('usermod', '-g', '2000', 'root'),
])
def test_system_wird_nie_geaendert(monkeypatch, cmd):
    rc, calls = run(monkeypatch, cmd)
    assert rc == 126 and cmd not in calls


def test_version_mindestens_6():
    assert int(g.VERSION) >= 6
