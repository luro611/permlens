"""Wächter-Script Version 9: Änderungen am Host (Mount-Punkte, Mapping, /etc/subuid und /etc/subgid)."""
import json
import os
import subprocess

import pytest

from test_waechter import g

CONF_9002 = ('arch: amd64\nhostname: ppm-test-share\nmp0: /srv/ppm-test/share,mp=/mnt/share\n'
             'mp1: local-lvm:vm-9002-disk-1,mp=/mnt/disk\nunprivileged: 1\n'
             '\n[vorher]\nhostname: ppm-test-share\nlxc.idmap: u 0 100000 65536\nsnaptime: 1700000000\n')
MAP = ['u:0:100000:1000', 'u:1000:1000:1', 'u:1001:101001:64535',
       'g:0:100000:1000', 'g:1000:1000:1', 'g:1001:101001:64535']
NAME = '9002-20261025-101500-abcdef'
ORIG_STOPPED = g.ct_stopped  # die Fixture ersetzt sie


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    lxc = tmp_path / 'lxc'
    lxc.mkdir()
    (lxc / '9002.conf').write_text(CONF_9002)
    (lxc / '9003.conf').write_text('hostname: privilegiert\nmp0: /srv/ppm-test/samba,mp=/srv/samba\n')
    (lxc / '112.conf').write_text('hostname: samba\nmp0: /mnt/appdata,mp=/data\nunprivileged: 1\n')
    monkeypatch.setattr(g, 'CONF_DIR', str(lxc))
    (tmp_path / 'freigabe' / 'neu').mkdir(parents=True)
    host = tmp_path / 'host-aendern-erlaubt'
    host.write_text(f'9001-9006  # Testcontainer\n{tmp_path / "freigabe"}\n')
    monkeypatch.setattr(g, 'HOST_FILE', str(host))
    write = tmp_path / 'schreiben-erlaubt'
    write.write_text('9001-9006\n')
    monkeypatch.setattr(g, 'WRITE_FILE', str(write))
    monkeypatch.setattr(g, 'BACKUP_DIR', str(tmp_path / 'sicherung'))
    (tmp_path / 'subuid').write_text('root:100000:65536\nroot:1000:1\n')
    (tmp_path / 'subgid').write_text('root:100000:65536\nroot:1000:1')
    monkeypatch.setattr(g, 'SUBID_FILES', {'subuid': str(tmp_path / 'subuid'), 'subgid': str(tmp_path / 'subgid')})
    monkeypatch.setattr(g, 'ct_stopped', lambda vmid: True)
    monkeypatch.setattr(g, 'log', lambda t: None)
    return tmp_path


def neu(tmp_path):
    return str(tmp_path / 'freigabe' / 'neu')


def conf(tmp_path, vmid='9002'):
    return (tmp_path / 'lxc' / f'{vmid}.conf').read_text()


def test_version_9_und_freigaben(capsys, umgebung):
    assert g.VERSION == '9'
    g.builtin(['version'])
    info = json.loads(capsys.readouterr().out)
    assert info['guard'] == '9' and info['host_ids'] == '9001-9006'
    assert info['host_paths'] == [str(umgebung / 'freigabe')] and info['write_ids'] == '9001-9006'


def test_ohne_schalter_datei_nichts(monkeypatch, umgebung):
    monkeypatch.setattr(g, 'HOST_FILE', str(umgebung / 'gibt-es-nicht'))
    assert g.check(['pct', 'set', '9002', '--delete', 'mp0']) is False
    assert g.check(['host-subid', 'subuid', '1000']) is False


# ---- erlaubte Formen
def erlaubt(tmp):
    return [
        ['pct', 'set', '9002', '--mp2', f'{neu(tmp)},mp=/mnt/neu'],
        ['pct', 'set', '9002', '--mp255', f'{neu(tmp)},mp=/mnt/neu,ro=1'],
        ['pct', 'set', '9002', '--delete', 'mp0'],
        ['host-idmap', '9002', *MAP],
        ['host-subid', 'subuid', '1000'], ['host-subid', 'subgid', '65533'],
        ['host-restore', '9002', NAME],
    ]


def test_erlaubte_formen(umgebung):
    for args in erlaubt(umgebung):
        assert g.check(args) == 'host', args


ABGELEHNT = [
    ['pct', 'set', '9002', '--mp1', '/a,mp=/b,backup=1'],      # weitere Optionen
    ['pct', 'set', '9002', '--mp1', '/a,mp=/b,ro=0'],
    ['pct', 'set', '9002', '--mp1', '/a,mp=/b,ro=1,ro=1'],
    ['pct', 'set', '9002', '--mp1', '/a b,mp=/b'],             # Leerzeichen
    ['pct', 'set', '9002', '--mp1', '/a:b,mp=/b'],             # Doppelpunkt (Speicher:Volume)
    ['pct', 'set', '9002', '--mp1', 'local-lvm:8,mp=/x'],      # neues Volume
    ['pct', 'set', '9002', '--mp1', '/srv/../etc,mp=/x'],
    ['pct', 'set', '9002', '--mp1', '/,mp=/x'], ['pct', 'set', '9002', '--mp1', '/srv,mp=/'],
    ['pct', 'set', '9002', '--mp1', '/srv/,mp=/x'], ['pct', 'set', '9002', '--mp1', 'srv,mp=/x'],
    ['pct', 'set', '9002', '--mp1', '/srv,ro=1,mp=/x'], ['pct', 'set', '9002', '--mp1', '/srv'],
    ['pct', 'set', '9002', '--mp256', '/srv,mp=/x'], ['pct', 'set', '9002', '--mp01', '/srv,mp=/x'],
    ['pct', 'set', '9002', '--rootfs', '/srv,mp=/x'], ['pct', 'set', '9002', '--memory', '512'],
    ['pct', 'set', '9002', '--unprivileged', '0'], ['pct', 'set', '9002', '--hookscript', 'local:snippets/x'],
    ['pct', 'set', '9002', '--delete', 'rootfs'], ['pct', 'set', '9002', '--delete', 'mp0,mp1'],
    ['pct', 'set', '9002', '--delete', 'unprivileged'],
    ['pct', 'set', '9002', '--mp1', '/srv,mp=/x', '--mp2', '/srv,mp=/y'],
    ['pct', 'set', '9002'], ['pct', 'set', 'abc', '--delete', 'mp0'],
    ['pct', 'start', '9002'], ['pct', 'shutdown', '9002'], ['pct', 'destroy', '9002'], ['pct', 'mount', '9002'],
    ['host-idmap', '9002'], ['host-idmap', '9002', 'u:0:100000:65536'],          # g fehlt
    ['host-idmap', '9002', 'u:0:0:65536', 'g:0:100000:65536'],                     # root durchgereicht
    ['host-idmap', '9002', 'u:0:0:1', 'u:1:100001:65535', 'g:0:100000:65536'],
    ['host-idmap', '9002', 'u:0:100000:1000', 'u:1001:101001:64535', 'g:0:100000:65536'],  # Lücke
    ['host-idmap', '9002', 'u:0:100000:65537', 'g:0:100000:65536'],                # zu groß
    ['host-idmap', '9002', 'u:0:100000:65535', 'g:0:100000:65536'],                # zu kurz
    ['host-idmap', '9002', 'u:0:100000:65534', 'u:65534:65534:2', 'g:0:100000:65536'],  # nobody durchgereicht
    ['host-idmap', '9002', 'u:0:100000:1000', 'u:1000:2000:1', 'u:1001:101001:64535', 'g:0:100000:65536'],
    ['host-idmap', '9002', 'u:0:100000:1000', 'u:1000:100500:1', 'u:1001:101001:64535', 'g:0:100000:65536'],  # Überlappung
    ['host-idmap', '9002', 'u:0:100000:65536', 'g:0:100000:65536', 'x:0:100000:1'],
    ['host-idmap', '9002', 'u 0 100000 65536', 'g 0 100000 65536'],
    ['host-subid', 'subuid', '0'], ['host-subid', 'subuid', '65534'], ['host-subid', 'subuid', '100000'],
    ['host-subid', 'shadow', '1000'], ['host-subid', 'subuid', '1000', '1'], ['host-subid', 'subuid', '-1'],
    ['host-restore', '9002', '9003-20261025-101500-abcdef'],                      # Sicherung eines anderen
    ['host-restore', '9002', '../9002-20261025-101500-abcdef'], ['host-restore', '9002', '9002'],
    ['host-restore', '9002', NAME, 'x'],
    ['pct', 'set', '112', '--delete', 'mp0'],                                      # nicht freigegeben
    ['host-idmap', '112', *MAP], ['host-restore', '112', '112-20261025-101500-abcdef'],
]


@pytest.mark.parametrize('args', ABGELEHNT)
def test_abgelehnt(args):
    assert not g.check(args)


def test_schreib_freigabe_reicht_nicht(monkeypatch, umgebung):
    """schreiben-erlaubt (Ändern im Container) gibt kein Ändern am Host frei und umgekehrt."""
    (umgebung / 'host-aendern-erlaubt').write_text('9002\n')
    (umgebung / 'schreiben-erlaubt').write_text('112\n')
    assert g.check(['pct', 'set', '112', '--delete', 'mp0']) is False
    assert g.check(['pct', 'set', '9002', '--delete', 'mp0']) == 'host'
    assert g.check(['pct', 'exec', '9002', '--', 'groupadd', '-g', '2000', 'media']) is False


def test_meldung_nicht_freigegeben(monkeypatch, capsys):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'pct set 112 --delete mp0')
    assert g.main() == 126
    assert 'host-aendern-erlaubt' in capsys.readouterr().err


# ---- Prüfungen vor dem Ausführen
def test_nur_gestoppt(monkeypatch):
    monkeypatch.setattr(g, 'ct_stopped', lambda vmid: False)
    assert 'läuft' in g.host_precheck(['pct', 'set', '9002', '--delete', 'mp0'])


def test_status_wird_gelesen(monkeypatch):
    for out, want in (('status: stopped\n', True), ('status: running\n', False)):
        monkeypatch.setattr(g.subprocess, 'run', lambda *a, o=out, **k: subprocess.CompletedProcess(a, 0, o, ''))
        assert ORIG_STOPPED('9002') is want


def test_gesperrt(umgebung):
    (umgebung / 'lxc' / '9002.conf').write_text('lock: backup\n' + CONF_9002)
    assert 'gesperrt' in g.host_precheck(['pct', 'set', '9002', '--delete', 'mp0'])


def test_container_auf_anderem_knoten():
    assert 'nicht' in g.host_precheck(['pct', 'set', '9004', '--delete', 'mp0'])


def test_mount_hinzu_pruefungen(umgebung):
    ok = ['pct', 'set', '9002', '--mp2', f'{neu(umgebung)},mp=/mnt/neu']
    assert g.host_precheck(ok) == ''
    assert 'belegt' in g.host_precheck(['pct', 'set', '9002', '--mp1', f'{neu(umgebung)},mp=/mnt/neu'])
    assert 'Einhängepunkt' in g.host_precheck(['pct', 'set', '9002', '--mp2', f'{neu(umgebung)},mp=/mnt/share'])
    assert 'freigegebenen' in g.host_precheck(['pct', 'set', '9002', '--mp2', '/etc,mp=/mnt/etc'])
    assert 'freigegebenen' in g.host_precheck(['pct', 'set', '9002', '--mp2', '/root,mp=/mnt/root'])
    assert 'freigegebenen' in g.host_precheck(['pct', 'set', '9002', '--mp2', f'{umgebung}/freigabe-2,mp=/x'])
    # Schon in einem anderen Container eingehängt: erlaubt, aber nur, wenn es den Ordner gibt
    assert 'gibt es auf dem Host nicht' in g.host_precheck(['pct', 'set', '9002', '--mp2', '/mnt/appdata,mp=/data'])
    assert 'gibt es auf dem Host nicht' in g.host_precheck(['pct', 'set', '9002', '--mp2', f'{neu(umgebung)}/x,mp=/x'])


def test_mount_hinzu_ohne_symlink(umgebung):
    os.symlink('/etc', umgebung / 'freigabe' / 'link')
    assert 'symbolische' in g.host_precheck(['pct', 'set', '9002', '--mp2', f'{umgebung}/freigabe/link,mp=/x'])


def test_mount_weg_nur_bind():
    assert g.host_precheck(['pct', 'set', '9002', '--delete', 'mp0']) == ''
    assert 'kein Bind-Mount' in g.host_precheck(['pct', 'set', '9002', '--delete', 'mp1'])  # Speicher-Volume
    assert 'kein Bind-Mount' in g.host_precheck(['pct', 'set', '9002', '--delete', 'mp7'])


def test_mapping_pruefungen(umgebung):
    assert g.host_precheck(['host-idmap', '9002', *MAP]) == ''
    assert 'unprivilegierte' in g.host_precheck(['host-idmap', '9003', *MAP])
    (umgebung / 'subgid').write_text('root:100000:65536\n')
    assert '/etc/subgid' in g.host_precheck(['host-idmap', '9002', *MAP])
    (umgebung / 'subuid').write_text('alice:1000:1\n')
    assert '/etc/subuid' in g.host_precheck(['host-idmap', '9002', *MAP])


def test_gedeckt_auch_aus_mehreren_eintraegen():
    assert g.covered([(100000, 1000), (101000, 64536)], 100000, 65536)
    assert not g.covered([(100000, 1000), (101001, 64535)], 100000, 65536)
    assert g.covered([(1000, 1)], 1000, 1) and not g.covered([(1000, 1)], 1001, 1)


# ---- Ausführen, Sicherung, Zurückspielen
def run(monkeypatch, capsys, *args):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', ' '.join(args))
    rc = g.main()
    out, err = capsys.readouterr()
    return rc, (json.loads(out) if out.strip() else {}), err


def test_mapping_setzen_und_zurueck(monkeypatch, capsys, umgebung):
    (umgebung / 'lxc' / '9002.conf').write_text(CONF_9002.replace('unprivileged: 1\n', 'unprivileged: 1\nlxc.idmap: u 0 100000 65536\nlxc.idmap: g 0 100000 65536\n'))
    vorher = conf(umgebung)
    rc, out, _ = run(monkeypatch, capsys, 'host-idmap', '9002', *MAP)
    assert rc == 0 and out['ok'] and out['changed']
    text = conf(umgebung)
    main, snap = text.split('\n[vorher]\n')
    assert main.endswith('lxc.idmap: g 1001 101001 64535\n')
    assert 'lxc.idmap: u 1000 1000 1' in main and 'lxc.idmap: u 0 100000 65536' not in main
    assert snap == 'hostname: ppm-test-share\nlxc.idmap: u 0 100000 65536\nsnaptime: 1700000000\n'  # Snapshot unberührt
    assert (umgebung / 'sicherung' / f"{out['backup']}.conf").read_text() == vorher
    assert oct(os.stat(umgebung / 'sicherung').st_mode & 0o777) == '0o700'

    rc, res, _ = run(monkeypatch, capsys, 'host-restore', '9002', out['backup'])
    assert rc == 0 and res['ok'] and conf(umgebung) == vorher
    rc, _, err = run(monkeypatch, capsys, 'host-restore', '9002', out['backup'])   # nur einmal
    assert rc == 126 and 'gibt es nicht' in err


def test_zurueck_nur_ohne_spaetere_aenderung(monkeypatch, capsys, umgebung):
    rc, out, _ = run(monkeypatch, capsys, 'host-idmap', '9002', *MAP)
    p = umgebung / 'lxc' / '9002.conf'
    p.write_text(p.read_text().replace('hostname: ppm-test-share\nmp0', 'hostname: anders\nmp0', 1))
    rc, _, err = run(monkeypatch, capsys, 'host-restore', '9002', out['backup'])
    assert rc == 126 and 'verändert' in err and 'hostname: anders' in p.read_text()


def test_mapping_ohne_snapshot(monkeypatch, capsys, umgebung):
    (umgebung / 'lxc' / '112.conf').write_text('hostname: samba\nunprivileged: 1\n\n')
    (umgebung / 'host-aendern-erlaubt').write_text('112\n')
    rc, out, _ = run(monkeypatch, capsys, 'host-idmap', '112', *MAP)
    assert rc == 0 and conf(umgebung, '112') == 'hostname: samba\nunprivileged: 1\n' + '\n'.join(
        f'lxc.idmap: {x.replace(":", " ")}' for x in MAP) + '\n'


def test_mount_hinzu_mit_sicherung(monkeypatch, capsys, umgebung):
    calls = []

    def fake(args, **kw):
        calls.append(args)
        with open(umgebung / 'lxc' / '9002.conf', 'a') as f:
            f.write('mp2: x\n')
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(g.subprocess, 'run', fake)
    rc, out, _ = run(monkeypatch, capsys, 'pct', 'set', '9002', '--mp2', f'{neu(umgebung)},mp=/mnt/neu,ro=1')
    assert rc == 0 and out['ok'] and out['backup'].startswith('9002-')
    assert calls == [['pct', 'set', '9002', '--mp2', f'{neu(umgebung)},mp=/mnt/neu,ro=1']]
    assert (umgebung / 'sicherung' / f"{out['backup']}.nachher").exists()


def test_fehlschlag_ohne_aenderung_keine_sicherung(monkeypatch, capsys, umgebung):
    monkeypatch.setattr(g.subprocess, 'run', lambda a, **k: subprocess.CompletedProcess(a, 255, '', 'unable to parse\n'))
    rc, out, _ = run(monkeypatch, capsys, 'pct', 'set', '9002', '--delete', 'mp0')
    assert rc == 1 and not out['ok'] and out['error'] == 'unable to parse'
    assert not list((umgebung / 'sicherung').iterdir())


def test_subid_anhaengen(monkeypatch, capsys, umgebung):
    rc, out, _ = run(monkeypatch, capsys, 'host-subid', 'subgid', '2000')
    assert rc == 0 and out == {'ok': True, 'added': True, 'line': 'root:2000:1'}
    assert (umgebung / 'subgid').read_text() == 'root:100000:65536\nroot:1000:1\nroot:2000:1\n'  # Zeilenende ergänzt
    rc, out, _ = run(monkeypatch, capsys, 'host-subid', 'subgid', '2000')
    assert out == {'ok': True, 'added': False}
    rc, out, _ = run(monkeypatch, capsys, 'host-subid', 'subuid', '1000')     # schon da
    assert out['added'] is False and (umgebung / 'subuid').read_text() == 'root:100000:65536\nroot:1000:1\n'


def test_abgelehnt_wird_protokolliert(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(g, 'log', seen.append)
    monkeypatch.setattr(g, 'ct_stopped', lambda vmid: False)
    rc, _, err = run(monkeypatch, capsys, 'pct', 'set', '9002', '--delete', 'mp0')
    assert rc == 126 and 'läuft' in err and seen[0].startswith('ABGELEHNT (HOST): pct set 9002')
