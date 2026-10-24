"""„Nachschauen“-Konsole (AP 6.3): sieht aus wie ein Terminal, kennt aber nur feste, lesende Befehle.

Was man eintippt, wird hier in genau eine Befehlsform des Wächters übersetzt (Wächter 8). Alles andere bekommt
eine freundliche Antwort, wohin man dafür geht. Eine freie Shell gibt es nicht: weder auf dem Host noch im LXC
noch in einer Docker-App (Entscheidungen 2026-10-21 und 2026-10-22). Was der Wächter nicht erlaubt, lehnt er
ohnehin ab; die Prüfung hier sorgt nur für verständliche Antworten.

Texte sind deutsch mit § als Platzhalter und werden in der Vorlage übersetzt."""
import json
import re
import shlex

from . import ssh
from .scan import FINDMNT, STAT, valid_path

NAME = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
NUM = re.compile(r'^[0-9]{1,10}$')
MAX_OUT = 64 * 1024

# Was es je Ziel gibt (für „hilfe“ und die Knöpfe unter dem Eingabefeld)
HELP = {
    'host': [['pct list', 'alle Container dieses Knotens'], ['pct config <Nr>', 'Einstellungen eines Containers'],
             ['cat /etc/subuid', 'Nummernbereiche (auch /etc/subgid, /etc/pve/storage.cfg)'],
             ['findmnt', 'eingehängte Dateisysteme'], ['getent passwd', 'Benutzer (auch getent group)'],
             ['stat <Ordner>', 'Besitzer und Rechte, nur Ordner, die ein Container einhängt'],
             ['getfacl <Ordner>', 'ACL, nur Ordner, die ein Container einhängt']],
    'lxc': [['id <Name>', 'Nummern und Gruppen eines Benutzers'], ['getent passwd <Name>', 'ein Benutzer (auch group)'],
            ['ls -ld <Pfad>', 'Besitzer und Rechte eines Eintrags'],
            ['ls -l <Ordner>', 'Inhalt eines Ordners, nur wenn Ändern freigegeben ist'],
            ['stat <Pfad>', 'Besitzer und Rechte'], ['getfacl <Pfad>', 'ACL eines Pfads'],
            ['df -h <Ordner>', 'Platz in einem eingehängten Ordner'], ['findmnt', 'eingehängte Ordner'],
            ['docker ps', 'Docker-Apps in diesem Container'], ['cat /etc/exports', 'NFS-Freigaben'],
            ['testparm -s', 'Samba-Einstellungen']],
    'app': [['id', 'als wer die App läuft'], ['ps', 'Programme der App mit ihren Nummern'],
            ['stat <Pfad>', 'Besitzer und Rechte, nur eingehängte Ordner der App'],
            ['inspect', 'Image, Benutzer, Ordner und Nummern-Variablen']],
}

ELSEWHERE = {  # häufige Wünsche, die es hier absichtlich nicht gibt
    'docker': 'Apps steuern (starten, stoppen, Logs, Shell) geht in Dockhand.',
    'bash': 'Eine Shell gibt es in PermLens nicht. Dafür: Proxmox-Weboberfläche → Konsole bzw. Dockhand.',
    'sh': 'Eine Shell gibt es in PermLens nicht. Dafür: Proxmox-Weboberfläche → Konsole bzw. Dockhand.',
    'cat': 'Dateiinhalte zeigt PermLens nicht (außer den wenigen Einstellungsdateien in „hilfe“).',
    'rm': 'Die Konsole liest nur. Ändern geht über „Ändern …“ mit Vorschau und Rückgängig.',
    'chown': 'Die Konsole liest nur. Ändern geht über „Ändern …“ mit Vorschau und Rückgängig.',
    'chmod': 'Die Konsole liest nur. Ändern geht über „Ändern …“ mit Vorschau und Rückgängig.',
    'setfacl': 'Die Konsole liest nur. Ändern geht über „Ändern …“ mit Vorschau und Rückgängig.',
    'usermod': 'Die Konsole liest nur. Benutzer ändern geht unter Container → Benutzer und Gruppen.',
    'useradd': 'Die Konsole liest nur. Benutzer ändern geht unter Container → Benutzer und Gruppen.',
}


def translate(kind, vmid, app, text):
    """Eingabe → (Wächter-Befehl, Darstellung) oder (None, Antwort als (Text, Werte …)).
    kind: 'host' | 'lxc' | 'app'. Darstellung: 'text', 'stat', 'acl', 'findmnt' oder 'json-…'."""
    try:
        w = shlex.split(text or '')
    except ValueError:
        return None, ('Die Eingabe ist nicht lesbar (Anführungszeichen?).',)
    if not w:
        return None, None
    if w[0] in ('hilfe', 'help', '?'):
        return None, 'hilfe'

    def path_arg(i=1):
        return w[i] if len(w) > i and valid_path(w[i]) else None

    pre = ['pct', 'exec', str(vmid), '--'] if kind == 'lxc' else []
    cmd = w[0]
    if kind == 'app':
        if w == ['id']:
            return ['docker-id', str(vmid), app], 'json-id'
        if w in (['ps'], ['top'], ['ps', 'aux'], ['ps', '-ef']):
            return ['docker-top', str(vmid), app], 'json-top'
        if w == ['inspect']:
            return ['docker-inspect', str(vmid), app], 'json-inspect'
        if cmd == 'stat' and 2 <= len(w) <= 9 and all(valid_path(p) for p in w[1:]):
            return ['docker-stat', str(vmid), app, *w[1:]], 'stat'
    if kind == 'host':
        if w == ['pct', 'list']:
            return ['pct', 'list'], 'text'
        if len(w) == 3 and w[:2] in (['pct', 'config'], ['pct', 'status']) and NUM.match(w[2]):
            return w, 'text'
        if len(w) == 2 and cmd == 'cat' and w[1] in ('/etc/subuid', '/etc/subgid', '/etc/pve/storage.cfg'):
            return w, 'text'
        if w in (['getent', 'passwd'], ['getent', 'group']):
            return w, 'text'
        if cmd == 'getfacl' and path_arg(len(w) - 1) and len(w) <= 3:
            return ['acl', w[-1]], 'acl'
    if kind == 'lxc':
        if len(w) == 2 and cmd == 'id' and (NAME.match(w[1]) or NUM.match(w[1])):
            return pre + w, 'text'
        if w in (['getent', 'passwd'], ['getent', 'group']):
            return pre + w, 'text'
        if len(w) == 3 and w[:2] in (['getent', 'passwd'], ['getent', 'group']) and (NAME.match(w[2]) or NUM.match(w[2])):
            return pre + w, 'text'
        if cmd == 'ls':
            flags = ''.join(x[1:] for x in w[1:] if x.startswith('-'))
            paths = [x for x in w[1:] if not x.startswith('-')]
            if len(paths) == 1 and valid_path(paths[0]) and set(flags) <= set('lnhda'):
                return pre + ['ls', '-lnd' if 'd' in flags else '-ln', paths[0]], 'list'
        if cmd == 'df' and len(w) >= 2 and path_arg(len(w) - 1) and all(x.startswith('-') for x in w[1:-1]):
            return pre + ['df', '-hP', w[-1]], 'text'
        if cmd == 'getfacl' and path_arg(len(w) - 1) and len(w) <= 3:
            return pre + ['getfacl', '-cpn', w[-1]], 'text'
        if w in (['cat', '/etc/exports'], ['testparm', '-s']):
            return pre + w, 'text'
        if w in (['docker', 'ps'], ['docker', 'ps', '-a']):
            return ['docker-ps', str(vmid)], 'json-ps'
    if kind in ('host', 'lxc'):
        if w == ['findmnt']:
            return pre + FINDMNT, 'findmnt'
        if cmd == 'stat' and 2 <= len(w) <= 9 and all(valid_path(p) for p in w[1:]):
            return pre + STAT + w[1:], 'stat'
    if cmd in ELSEWHERE:
        return None, (ELSEWHERE[cmd],)
    return None, ('„§“ gibt es hier nicht. „hilfe“ zeigt, was geht.', cmd)


def _stat_lines(out):
    rows = []
    for line in out.splitlines():
        f = line.split('|', 7)
        if len(f) == 8:
            user = f[4] if f[4] not in ('', 'UNKNOWN', '?') else '–'
            group = f[5] if f[5] not in ('', 'UNKNOWN', '?') else '–'
            rows.append(f'{f[0]}  {f[1]:>4}  {f[2]}:{f[3]} ({user}:{group})  {f[6]}  {f[7]}')
    return '\n'.join(rows) or out


def _findmnt_lines(out):
    try:
        items = json.loads(out).get('filesystems') or []
    except (ValueError, AttributeError):
        return out
    rows = []

    def walk(xs, depth):
        for x in xs or []:
            rows.append(f"{'  ' * depth}{x.get('target', '')}  {x.get('fstype', '')}  {x.get('source', '')}")
            walk(x.get('children'), depth + 1)
    walk(items, 0)
    return '\n'.join(rows)


def _acl_lines(out):
    try:
        d = json.loads(out)
    except ValueError:
        return out
    rows = [f"# file: {d.get('path', '')}"]
    for key, prefix in (('access', ''), ('default', 'default:')):
        for e in d.get(key) or []:
            tag = {'user_obj': 'user', 'group_obj': 'group'}.get(e['tag'], e['tag'])
            rows.append(f"{prefix}{tag}:{'' if e.get('id') is None else e['id']}:{e['perm']}")
    return '\n'.join(rows)


def _json_lines(view, out):
    try:
        d = json.loads(out)
    except ValueError:
        return out
    if d.get('error'):
        return d['error']
    if view == 'json-id':
        return d.get('id', '')
    if view == 'json-top':
        return '\n'.join(['UID   GID   COMMAND'] + [f"{p['uid']:<5} {p['gid']:<5} {p['comm']}" for p in d.get('processes') or []])
    if view == 'json-ps':
        if not d.get('docker'):
            return '(no Docker)'
        return '\n'.join([f"{a['name']}  {a['image']}  {a['status']}" for a in d.get('apps') or []]) or '(no apps)'
    if view == 'json-inspect':
        rows = [f"Image:  {d.get('image', '')}", f"State:  {d.get('state', '')}",
                f"User:   {d.get('user') or '(not set: root)'}"]
        rows += [f"Env:    {k}={v}" for k, v in (d.get('env') or {}).items()]
        rows += [f"Mount:  {m['source']} -> {m['destination']} ({m['type']}, {'rw' if m['rw'] else 'ro'})"
                 for m in d.get('mounts') or []]
        return '\n'.join(rows)
    return out


def run(host, port, kind, vmid, app, text):
    """Eingabe ausführen. Ergebnis: {input, cmd (Wächter-Befehl als Text), out, error, help}."""
    res = {'input': text, 'cmd': '', 'out': '', 'error': None, 'help': False}
    args, view = translate(kind, vmid, app, text)
    if args is None:
        if view == 'hilfe':
            res['help'] = True
        else:
            res['error'] = view
        return res
    res['cmd'] = ' '.join(shlex.quote(a) for a in args)
    r = ssh.run(host, args, port, timeout=30)
    out = (r.out or '')[:MAX_OUT]
    if r.rc == ssh.DENIED:
        res['error'] = (r.err.strip().replace('permlens-guard: ', 'Wächter: ') or 'Der Wächter hat den Befehl abgelehnt.',)
        if 'Befehl nicht erlaubt' in r.err:
            res['error'] = ('Der Wächter auf dem Proxmox kennt diesen Befehl nicht. Für die Konsole braucht er Version 8 '
                            '(Einstellungen → Neu einrichten).',)
        return res
    if r.rc == 124:
        res['error'] = ('Keine Antwort. Ist das NAS ausgeschaltet?',)
        return res
    if view == 'stat':
        res['out'] = _stat_lines(out)
    elif view == 'findmnt':
        res['out'] = _findmnt_lines(out)
    elif view == 'acl':
        res['out'] = _acl_lines(out)
    elif view.startswith('json-'):
        res['out'] = _json_lines(view, out)
    else:
        res['out'] = out
    if not r.ok and not res['out'].strip():
        res['out'] = (r.err or '').strip()[:4000] or f'(Rückgabewert {r.rc})'
    return res
