"""Wächter-Script Version 5: Besitzer, Rechte, ACL und Schreibtest – nur in eingehängten Ordnern und /home."""
import subprocess

import pytest

from test_waechter import g

T = '.permlens-schreibtest-abcdef012345'
SP = ['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', '--']


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    (tmp_path / '9005.conf').write_text('mp0: /srv/ppm-test/bind-idmap,mp=/mnt/test\n'
                                        'mp1: /srv/ppm-test/share,mp=/mnt/share,ro=0\n'
                                        'lxc.mount.entry: /mnt/nas mnt/nas none bind,create=dir 0 0\n'
                                        '\n[alt]\nmp9: /x,mp=/mnt/alt\n')
    (tmp_path / '9002.conf').write_text('mp0: local-lvm:vm-9002-disk-1,mp=/\n')
    monkeypatch.setattr(g, 'CONF_DIR', str(tmp_path))
    f = tmp_path / 'schreiben-erlaubt'
    f.write_text('9001-9006\n')
    monkeypatch.setattr(g, 'WRITE_FILE', str(f))


def ct(*cmd, vmid='9005'):
    return ['pct', 'exec', vmid, '--', *cmd]


ERLAUBT = [
    ct('chown', '1000:1000', '/mnt/share'),
    ct('chown', '0:0', '/mnt/test/unterordner'),          # root für Rückgängig
    ct('chmod', '2775', '/mnt/share'),
    ct('chmod', '750', '/home/alice'),
    ct('setfacl', '-m', 'u:1001:r-x', '/mnt/share'),
    ct('setfacl', '-m', 'g:2000:rwx', '/mnt/nas/medien'),  # Ziel aus lxc.mount.entry
    ct('setfacl', '-x', 'u:1001', '/mnt/share'),
    ct('setfacl', '-b', '/mnt/share'),
    ct(*SP, 'touch', f'/mnt/share/{T}'),
    ct(*SP, 'rm', '-f', f'/mnt/share/{T}'),
    ct('rm', '-f', f'/mnt/share/{T}'),
]

ABGELEHNT = [
    ct('chown', '1000:1000', '/etc'),                     # Systemordner
    ct('chown', '1000:1000', '/mnt'),                     # oberhalb des Mounts
    ct('chown', '1000:1000', '/mnt/sharex'),              # nur Präfix, nicht darunter
    ct('chown', '1000:1000', '/mnt/alt'),                 # nur im Snapshot
    ct('chown', '1000:1000', '/'),
    ct('chown', '1000:1000', '/mnt/share', '/etc'),
    ct('chown', '-R', '1000:1000', '/mnt/share'),         # rekursiv erst später
    ct('chown', 'alice:alice', '/mnt/share'),             # nur Nummern
    ct('chown', '65534:65534', '/mnt/share'),             # nobody
    ct('chown', '1000', '/mnt/share'),
    ct('chmod', '4755', '/mnt/share'),                    # setuid nie
    ct('chmod', 'g+w', '/mnt/share'),                     # nur oktal
    ct('chmod', '777', '/mnt/share/../../etc'),
    ct('setfacl', '-m', 'u:alice:rwx', '/mnt/share'),
    ct('setfacl', '-m', 'u:1001:rwx,u:1002:rwx', '/mnt/share'),
    ct('setfacl', '-m', 'd:u:1001:rwx', '/mnt/share'),
    ct('setfacl', '-b', '/etc'),
    ct(*SP, 'touch', '/mnt/share/andere-datei'),          # nur die Testdatei
    ct(*SP, 'rm', '-f', '/mnt/share/wichtig.txt'),
    ct('rm', '-f', '/mnt/share/wichtig.txt'),
    ct('rm', '-rf', f'/mnt/share/{T}'),
    ct(*SP, 'sh', '-c', 'id'),
    ct('chmod', '755', '/mnt/share', vmid='112'),         # nicht freigegeben
]


@pytest.mark.parametrize('args', ERLAUBT)
def test_form_erlaubt(args):
    assert g.check(args) == 'write'
    assert g.inside_targets(args[2], g.write_path(args[4:]))


@pytest.mark.parametrize('args', ABGELEHNT)
def test_abgelehnt(args):
    p = g.write_path(args[4:]) if g.check(args) == 'write' else None
    assert g.check(args) != 'write' or not g.inside_targets(args[2], p)


def test_getfacl_lesen_ohne_freigabe(tmp_path, monkeypatch):
    monkeypatch.setattr(g, 'WRITE_FILE', str(tmp_path / 'fehlt'))
    assert g.check(ct('getfacl', '-cpn', '/mnt/share')) is True
    assert not g.check(ct('getfacl', '-R', '/')) and not g.check(ct('chmod', '755', '/mnt/share'))


def test_ziele_aus_der_konfiguration():
    assert g.mount_targets('9005') == {'/home', '/mnt/test', '/mnt/share', '/mnt/nas'}
    assert g.mount_targets('9002') == {'/home'}  # Wurzel „/“ zählt nie
    assert g.mount_targets('4711') == {'/home'}


class Lauf:
    def __init__(self, real):
        self.real, self.calls = real, []

    def __call__(self, args, **kw):
        self.calls.append(args)
        if 'realpath' in args:
            return subprocess.CompletedProcess(args, 0 if self.real else 1, (self.real or '') + '\n', '')
        return subprocess.CompletedProcess(args, 0, '', '')


def run(monkeypatch, cmd, real):
    lauf = Lauf(real)
    monkeypatch.setattr(g.subprocess, 'run', lauf)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', ' '.join(cmd))
    return g.main(), lauf.calls


def test_ausfuehren_nach_pruefung(monkeypatch):
    cmd = ct('chmod', '2775', '/mnt/share')
    rc, calls = run(monkeypatch, cmd, '/mnt/share')
    assert rc == 0 and calls == [ct('realpath', '-e', '/mnt/share'), cmd]


def test_symlink_wird_abgelehnt(monkeypatch, capsys):
    rc, calls = run(monkeypatch, ct('chown', '1000:1000', '/mnt/share/link'), '/etc')
    assert rc == 126 and len(calls) == 1 and 'symbolische' in capsys.readouterr().err


def test_pfad_fehlt(monkeypatch):
    rc, calls = run(monkeypatch, ct('chmod', '755', '/mnt/share/gibtsnicht'), None)
    assert rc == 126 and len(calls) == 1


def test_ausserhalb_der_mounts_ohne_aufruf(monkeypatch, capsys):
    rc, calls = run(monkeypatch, ct('chown', '1000:1000', '/etc'), '/etc')
    assert rc == 126 and calls == [] and 'eingehängten Ordnern' in capsys.readouterr().err


def test_schreibtest_prueft_den_ordner(monkeypatch):
    cmd = ct(*SP, 'touch', f'/mnt/share/{T}')
    rc, calls = run(monkeypatch, cmd, '/mnt/share')
    assert rc == 0 and calls == [ct('realpath', '-e', '/mnt/share'), cmd]


def test_version_mindestens_5():
    assert int(g.VERSION) >= 5
