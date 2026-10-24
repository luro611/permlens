"""Wächter-Script Version 4: Schalter-Datei mit freigegebenen Containern, Gruppe anlegen und löschen."""
import json
import subprocess

import pytest

from test_waechter import g


@pytest.fixture
def schalter(tmp_path, monkeypatch):
    """Schalter-Datei an einem Testort. Ohne Aufruf von write() gibt es sie nicht."""
    f = tmp_path / 'schreiben-erlaubt'
    monkeypatch.setattr(g, 'WRITE_FILE', str(f))

    def write(text):
        f.write_text(text)
    return write


ADD = ['pct', 'exec', '9003', '--', 'groupadd', '-g', '2001', 'projekt']
DEL = ['pct', 'exec', '9003', '--', 'groupdel', 'projekt']


def test_ohne_schalter_datei_kein_schreiben(schalter):
    assert g.write_ranges() is None
    assert not g.check(ADD) and not g.check(DEL)


@pytest.mark.parametrize('text', ['', '\n# nur ein Kommentar\n', 'alle', '9010', '9004-9002', '99'])
def test_leer_oder_unpassend_kein_schreiben(schalter, text):
    schalter(text)
    assert not g.check(ADD)


@pytest.mark.parametrize('text', ['9003', '9001-9006', '112, 9003', '# Test\n9001-9002\n9003  # samba\n', '9000-9999'])
def test_freigegeben(schalter, text):
    schalter(text)
    assert g.check(ADD) == 'write' and g.check(DEL) == 'write'


def test_freigabe_gilt_nur_fuer_diese_container(schalter):
    schalter('9001-9002')
    assert not g.check(ADD)
    assert g.check(['pct', 'exec', '9002', '--', 'groupadd', '-g', '2001', 'projekt']) == 'write'


def test_lesen_braucht_keine_freigabe(schalter):
    schalter('')
    assert g.check(['pct', 'exec', '9003', '--', 'getent', 'group']) is True


@pytest.mark.parametrize('cmd', [
    ['groupadd', '-g', '999', 'projekt'],          # System-GID
    ['groupadd', '-g', '0', 'projekt'],
    ['groupadd', '-g', '65534', 'projekt'],        # nobody
    ['groupadd', '-g', '60000', 'projekt'],
    ['groupadd', '-g', '2001', 'Projekt'],         # Großbuchstaben
    ['groupadd', '-g', '2001', '-projekt'],
    ['groupadd', '-g', '2001', 'a;id'],
    ['groupadd', '-g', '2001', 'x' * 33],
    ['groupadd', '-g', '2001', 'projekt', '-o'],   # zusätzliche Schalter
    ['groupadd', '-o', '-g', '2001', 'projekt'],
    ['groupadd', 'projekt'],
    ['groupadd', '-g', '2001x', 'projekt'],
    ['groupdel', '-f', 'projekt'],
    ['groupdel', 'root', 'projekt'],
    ['useradd', 'bob'],
])
def test_nur_genau_diese_formen(schalter, cmd):
    schalter('9001-9006')
    assert not g.check(['pct', 'exec', '9003', '--'] + cmd)


def test_schreiben_nur_im_container(schalter):
    schalter('9001-9006')
    assert not g.check(['groupadd', '-g', '2001', 'projekt'])


def test_version_meldet_freigabe(schalter, monkeypatch, capsys):
    schalter('9001-9006\n112\n')
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'version')
    assert g.main() == 0
    info = json.loads(capsys.readouterr().out)
    assert info['guard'] == g.VERSION and info['write_enabled'] is True and info['write_ids'] == '9001-9006,112'


def test_version_ohne_freigabe(schalter, monkeypatch, capsys):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'version')
    g.main()
    info = json.loads(capsys.readouterr().out)
    assert info['write_enabled'] is False and info['write_ids'] == ''


def test_klare_meldung_ohne_freigabe(schalter, monkeypatch, capsys):
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', ' '.join(ADD))
    assert g.main() == 126
    assert 'nicht freigegeben' in capsys.readouterr().err


class Lauf:
    """Ersatz für subprocess.run: merkt sich die Aufrufe, getent liefert die angegebene Gruppenzeile."""
    def __init__(self, gruppe):
        self.gruppe, self.calls = gruppe, []

    def __call__(self, args, **kw):
        self.calls.append(args)
        if args[-3:-1] == ['getent', 'group']:
            return subprocess.CompletedProcess(args, 0 if self.gruppe else 2, self.gruppe, '')
        return subprocess.CompletedProcess(args, 0, '', '')


def test_groupdel_prueft_gid_im_container(schalter, monkeypatch, capsys):
    schalter('9003')
    lauf = Lauf('projekt:x:2001:\n')
    monkeypatch.setattr(g.subprocess, 'run', lauf)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', ' '.join(DEL))
    assert g.main() == 0
    assert lauf.calls == [['pct', 'exec', '9003', '--', 'getent', 'group', 'projekt'], DEL]


@pytest.mark.parametrize('zeile', ['sudo:x:27:bob\n', 'nogroup:x:65534:\n', ''])
def test_groupdel_lehnt_systemgruppen_ab(schalter, monkeypatch, capsys, zeile):
    schalter('9003')
    lauf = Lauf(zeile)
    monkeypatch.setattr(g.subprocess, 'run', lauf)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', 'pct exec 9003 -- groupdel x')
    assert g.main() == 126
    assert len(lauf.calls) == 1  # nur die Prüfung, kein groupdel


def test_groupadd_laeuft(schalter, monkeypatch):
    schalter('9003')
    lauf = Lauf('')
    monkeypatch.setattr(g.subprocess, 'run', lauf)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', ' '.join(ADD))
    assert g.main() == 0
    assert lauf.calls == [ADD]
