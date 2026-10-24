"""SSH-Verbindung zum Proxmox-Host.

PermLens hat einen eigenen Schlüssel in data/ssh/. Auf dem Host ist dieser Schlüssel fest an das Wächter-Script
/usr/local/sbin/permlens-guard gebunden (siehe host/permlens-guard). PermLens schickt deshalb nur einfache
Befehle als Liste; der Wächter entscheidet, ob sie ausgeführt werden.

Der Host-Schlüssel des Proxmox wird beim ersten Verbinden gespeichert (data/ssh/known_hosts) und danach geprüft."""
import json
import re
import shlex
import subprocess
from dataclasses import dataclass

from .. import config

GUARD = '/usr/local/sbin/permlens-guard'
DIR = config.DATA / 'ssh'
KEY = DIR / 'id_ed25519'
KNOWN = DIR / 'known_hosts'
TIMEOUT = 75  # etwas länger als das Zeitlimit des Wächters (60 s)
DENIED = 126  # Rückgabewert des Wächters für „nicht erlaubt“
HOST_OK = re.compile(r'^[A-Za-z0-9.:-]+$')


@dataclass
class Result:
    rc: int
    out: str
    err: str

    @property
    def ok(self):
        return self.rc == 0


def has_key():
    return KEY.exists() and KEY.with_suffix('.pub').exists()


def public_key():
    return KEY.with_suffix('.pub').read_text().strip() if has_key() else ''


def generate_key():
    """Neues Schlüsselpaar erzeugen. Ein altes wird ersetzt (danach muss die Zeile auf dem Host erneuert werden)."""
    DIR.mkdir(parents=True, exist_ok=True)
    DIR.chmod(0o700)
    for f in (KEY, KEY.with_suffix('.pub')):
        f.unlink(missing_ok=True)
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'permlens', '-f', str(KEY)],
                   check=True, capture_output=True, timeout=30)


def authorized_line(lxc_ip=''):
    """Zeile für /root/.ssh/authorized_keys auf dem Proxmox-Host."""
    opts = f'command="{GUARD}",restrict'
    if lxc_ip:
        opts += f',from="{lxc_ip}"'
    return f'{opts} {public_key()}'


def valid_host(host):
    return bool(host) and bool(HOST_OK.match(host)) and not host.startswith('-')


def _ssh(host, port, remote, timeout, data=None):
    cmd = ['ssh', '-i', str(KEY), '-p', str(int(port)), '-T',
           '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
           '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={KNOWN}', '-o', 'HashKnownHosts=no',
           '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=10', '-o', 'LogLevel=ERROR',
           # eine Verbindung für viele Befehle wiederverwenden (Scan wird dadurch viel schneller)
           '-o', 'ControlMaster=auto', '-o', 'ControlPath=/tmp/permlens-%C', '-o', 'ControlPersist=60',
           f'root@{host}', remote]
    try:
        if data is None:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        else:  # z. B. eine Sicherung für permlens-restore
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=data)
        return Result(p.returncode, p.stdout, p.stderr.strip())
    except subprocess.TimeoutExpired:
        return Result(124, '', f'Zeitlimit von {timeout} Sekunden überschritten')


def run(host, args, port=22, timeout=TIMEOUT, data=None):
    """Einen Befehl über den Wächter ausführen. args ist eine Liste, z. B. ['pct', 'config', '112'].
    data: Text für die Standard-Eingabe (nur für permlens-restore)."""
    if not has_key():
        return Result(255, '', 'Es gibt noch keinen SSH-Schlüssel.')
    if not valid_host(host):
        return Result(255, '', 'Ungültige Host-Adresse.')
    return _ssh(host, port, shlex.join(args), timeout, data)


def host_fingerprint(host, port=22):
    """Fingerabdruck des gespeicherten Host-Schlüssels (z. B. 'SHA256:…') oder ''."""
    if not KNOWN.exists() or not valid_host(host):
        return ''
    name = host if int(port) == 22 else f'[{host}]:{int(port)}'
    p = subprocess.run(['ssh-keygen', '-l', '-F', name, '-f', str(KNOWN)], capture_output=True, text=True, timeout=10)
    m = re.search(r'(SHA256:\S+)', p.stdout)
    return m.group(1) if m else ''


def _known_name(host, port):
    return host if int(port) == 22 else f'[{host}]:{int(port)}'


def _other_lines(host, port):
    """Zeilen in known_hosts, die nicht zu diesem Host gehören (gespeichert wird immer im Klartext, nie gehasht)."""
    name = _known_name(host, port)
    lines = KNOWN.read_text().splitlines() if KNOWN.exists() else []
    return [x for x in lines if x.strip() and name not in x.split(' ', 1)[0].split(',')]


def forget_host(host, port=22):
    """Gespeicherten Host-Schlüssel nur dieses Hosts löschen, die der anderen Proxmox bleiben."""
    if KNOWN.exists():
        KNOWN.write_text(''.join(x + '\n' for x in _other_lines(host, port)))


def explain(r):
    """Fehler aus SSH in verständliche Sätze übersetzen (deutscher Quelltext, wird in der Vorlage übersetzt)."""
    e = r.err
    if r.rc == DENIED:
        return 'Der Wächter hat den Befehl abgelehnt.'
    if 'Permission denied' in e:
        return 'Der Proxmox kennt den Schlüssel von PermLens nicht. Ist die Zeile in authorized_keys eingetragen?'
    if 'Host key verification failed' in e or 'REMOTE HOST IDENTIFICATION HAS CHANGED' in e:
        return 'Der Proxmox meldet sich mit einem anderen Host-Schlüssel als beim ersten Mal.'
    if 'Connection refused' in e:
        return 'Der Proxmox lehnt die Verbindung ab. Stimmen Adresse und Port?'
    if 'timed out' in e or r.rc == 124 or 'No route to host' in e:
        return 'Der Proxmox antwortet nicht. Stimmt die Adresse, ist er eingeschaltet?'
    if 'not found' in e and GUARD in e or 'No such file' in e:
        return 'Das Wächter-Script fehlt auf dem Proxmox.'
    return e or f'Unbekannter Fehler (Rückgabewert {r.rc}).'


def guard_info(host, port=22):
    """Antwort des Wächters auf 'version' (z. B. {'guard': '2', ...}) und das SSH-Ergebnis."""
    r = run(host, ['version'], port, timeout=20)
    info = {}
    if r.ok:
        try:
            info = json.loads(r.out)
        except ValueError:
            pass
    return info, r


def test_connection(host, port=22):
    """Verbindungstest in drei Schritten. Gibt eine Liste von Prüfungen zurück: {name, ok, detail}.
    Die erste Prüfung enthält zusätzlich 'guard' (Version des Wächters oder '')."""
    steps = []
    info, r = guard_info(host, port)
    steps.append({'name': 'Verbindung und Wächter-Script', 'ok': bool(info.get('guard')),
                  'detail': ('Wächter Version §', info['guard']) if info.get('guard') else explain(r),
                  'guard': str(info.get('guard') or ''), 'write_ids': str(info.get('write_ids') or '')})
    if not info.get('guard'):
        return steps
    r = run(host, ['pct', 'list'], port, timeout=30)
    n = max(0, len(r.out.strip().splitlines()) - 1) if r.ok else 0
    steps.append({'name': 'Container lesen', 'ok': r.ok, 'detail': ('§ Container gefunden', n) if r.ok else explain(r)})
    r = run(host, ['id'], port, timeout=20)
    steps.append({'name': 'Wächter lehnt fremde Befehle ab', 'ok': r.rc == DENIED,
                  'detail': 'Ein nicht erlaubter Befehl wurde abgelehnt.' if r.rc == DENIED
                  else 'Achtung: Ein nicht erlaubter Befehl wurde NICHT abgelehnt. Ist der Schlüssel an das Wächter-Script gebunden?'})
    return steps


def trust_host(host, port, hostkey):
    """Host-Schlüssel des Proxmox fest eintragen (kommt bei der Einrichtung direkt vom Host)."""
    DIR.mkdir(parents=True, exist_ok=True)
    DIR.chmod(0o700)
    KNOWN.write_text(''.join(x + '\n' for x in _other_lines(host, port)) + f'{_known_name(host, port)} {hostkey}\n')
