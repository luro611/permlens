"""Tests für host/permlens-guard: Was erlaubt ist, läuft; alles andere wird abgelehnt."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / 'host' / 'permlens-guard'
_loader = importlib.machinery.SourceFileLoader('permlens_guard', str(GUARD))
_spec = importlib.util.spec_from_loader('permlens_guard', _loader)
g = importlib.util.module_from_spec(_spec)
_loader.exec_module(g)
FMT = g.STAT_FORMAT


@pytest.fixture(autouse=True)
def lxc_configs(tmp_path, monkeypatch):
    """Zwei Container-Konfigurationen wie in /etc/pve/lxc. /alt steht nur in einem Snapshot."""
    (tmp_path / '112.conf').write_text('hostname: samba\nmp0: /mnt/appdata,mp=/data\nmp1: local-lvm:vm-112-disk-1,mp=/x\n'
                                       '\n[vor-update]\nmp9: /alt,mp=/alt\n')
    (tmp_path / '9005.conf').write_text('mp1: /srv/ppm-test/share,mp=/mnt/share,ro=1\n'
                                        'lxc.mount.entry: /mnt/nas mnt/nas none bind,create=dir 0 0\n')
    (tmp_path / 'notizen.txt').write_text('mp0: /root,mp=/root\n')
    monkeypatch.setattr(g, 'CONF_DIR', str(tmp_path))

ERLAUBT = [
    ['version'],
    ['acl', '/mnt/appdata'],
    ['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'],
    ['pct', 'list'],
    ['pct', 'config', '112'],
    ['pct', 'status', '9001'],
    ['cat', '/etc/subuid'],
    ['cat', '/etc/pve/storage.cfg'],
    ['getent', 'passwd'],
    g.FINDMNT,
    ['stat', '-c', FMT, '/mnt/appdata', '/srv/ppm-test/share'],
    ['pct', 'exec', '112', '--', 'getent', 'passwd'],
    ['pct', 'exec', '112', '--', 'testparm', '-s'],
    ['pct', 'exec', '9005', '--', 'stat', '-c', FMT, '/mnt/share'],
    ['pct', 'exec', '9005', '--', 'stat', '-c', FMT, '/etc'],  # im Container: jeder Pfad
    ['pct', 'exec', '140', '--'] + g.FINDMNT,
    # Version 3
    ['stat', '-c', FMT, '/mnt/nas'],                     # Quelle aus lxc.mount.entry
    ['acl', '/mnt/nas'],
    ['pct', 'exec', '9005', '--', 'cat', '/etc/exports'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', '--', 'test', '-w', '/mnt/test'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=0', '--regid=0', '--groups=1000,2000', '--', 'test', '-r', '/mnt/test'],
]

ABGELEHNT = [
    [],
    ['id'],
    ['rm', '-rf', '/'],
    ['cat', '/etc/shadow'],
    ['cat', '/etc/subuid', '/etc/shadow'],
    ['pct', 'config', '112; rm -rf /'],
    ['pct', 'config', '../112'],
    ['pct', 'destroy', '112'],
    ['pct', 'exec', '112', '--', 'bash'],
    ['pct', 'exec', '112', '--', 'sh', '-c', 'id'],
    ['pct', 'exec', '112', 'getent', 'passwd'],          # ohne --
    ['pct', 'exec', '112', '--', 'chown', 'root', '/'],
    ['stat', '-c', '%n', '/etc/shadow'],                  # anderes Format
    ['stat', '-c', FMT, 'relativ'],
    ['stat', '-c', FMT, '/mnt/../etc/shadow'],
    ['stat', '-c', FMT, '/mnt/$(id)'],
    ['stat', '-c', FMT, '/mnt/a;b'],
    ['acl', '/mnt/a`id`'],
    # auf dem Host nur Mount-Quellen von Containern
    ['stat', '-c', FMT, '/root'],
    ['stat', '-c', FMT, '/mnt/appdata', '/etc/pve/priv'],
    ['stat', '-c', FMT, '/mnt/appdata/unterordner'],
    ['stat', '-c', FMT, '/alt'],                          # nur im Snapshot
    ['stat', '-c', FMT, 'local-lvm:vm-112-disk-1'],
    ['acl', '/etc/pve/priv'],
    ['acl', '/root'],
    ['pvesh', 'set', '/nodes'],
    ['findmnt'],
    ['pct', 'list', '--extra'],
    # Version 3: nur genau diese Formen
    ['cat', '/etc/exports'],                              # nur im Container, nicht auf dem Host
    ['pct', 'exec', '9005', '--', 'cat', '/etc/exports', '/etc/shadow'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', '--', 'sh', '-c', 'id'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', '--', 'test', '-e', '/x'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', '--', 'test', '-w', '/x;id'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=abc', '--regid=1000', '--clear-groups', '--', 'test', '-w', '/x'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--groups=1000,$(id)', '--', 'test', '-w', '/x'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--init-groups', '--', 'test', '-w', '/x'],
    ['pct', 'exec', '9004', '--', 'setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', '--', 'test', '-w', '/x', '-a', '-r', '/y'],
    ['stat', '-c', FMT, 'mnt/nas'],                       # Ziel aus lxc.mount.entry ist kein Host-Pfad
]


@pytest.mark.parametrize('args', ERLAUBT)
def test_erlaubt(args):
    assert g.check(args)


@pytest.mark.parametrize('args', ABGELEHNT)
def test_abgelehnt(args):
    assert not g.check(args)


def test_ablehnung_beim_aufruf(monkeypatch, capsys):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'cat /etc/shadow')
    assert g.main() == 126
    assert 'nicht erlaubt' in capsys.readouterr().err


def test_kaputte_anfuehrungszeichen(monkeypatch):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'pct config "112')
    assert g.main() == 126


def test_version(monkeypatch, capsys):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'version')
    assert g.main() == 0
    assert f'"guard": "{g.VERSION}"' in capsys.readouterr().out


def test_lange_pfade_sind_schnell():
    """Die Pfadprüfung darf bei langen, ungültigen Eingaben nicht hängen bleiben."""
    assert not g.safe_path('/' + 'a/' * 5000 + '!')


def test_acl_ohne_acl(tmp_path, capsys):
    assert g.acl(str(tmp_path)) == 0
    assert '"access": []' in capsys.readouterr().out


def test_script_ist_ausfuehrbar():
    assert os.access(GUARD, os.X_OK)


def test_ohne_konfigurationen_kein_host_pfad(monkeypatch, tmp_path):
    monkeypatch.setattr(g, 'CONF_DIR', str(tmp_path / 'fehlt'))
    assert not g.check(['stat', '-c', FMT, '/mnt/appdata'])
