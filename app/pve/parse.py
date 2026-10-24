"""Ausgaben vom Proxmox-Host in Python-Daten übersetzen. Reine Funktionen ohne Verbindung (gut testbar)."""
import json
import re
from urllib.parse import unquote

_KV = re.compile(r'^([A-Za-z0-9_.]+):\s*(.*)$')
_MP = re.compile(r'^mp\d+$')


def resources(text):
    """Ausgabe von `pvesh get /cluster/resources --type vm --output-format json` → Liste von Gästen."""
    out = []
    for r in json.loads(text or '[]'):
        if r.get('type') not in ('lxc', 'qemu') or r.get('template'):
            continue
        out.append({'vmid': int(r['vmid']), 'type': r['type'], 'name': r.get('name', ''),
                    'status': r.get('status', ''), 'node': r.get('node', ''),
                    'tags': [t for t in re.split(r'[;, ]+', r.get('tags') or '') if t]})
    return sorted(out, key=lambda g: g['vmid'])


def _options(value):
    """'a,b=c,d=e' → (erster Wert, {b: c, d: e}). Der erste Teil ohne '=' ist bei mpX die Quelle."""
    parts = value.split(',')
    first, opts = '', {}
    for i, p in enumerate(parts):
        if '=' in p:
            k, v = p.split('=', 1)
            opts[k] = v
        elif i == 0:
            first = p
        else:
            opts[p] = True
    return first, opts


def pct_config(text):
    """Ausgabe von `pct config <ID>` → Einstellungen. Abschnitte von Snapshots ([name]) werden übersprungen."""
    cfg = {'hostname': '', 'unprivileged': False, 'features': {}, 'mounts': [], 'idmap': [],
           'ip': '', 'onboot': False, 'raw': {}, 'lines': [], 'description': '', 'snapshots': []}
    snap = False
    for line in (text or '').splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            snap = True  # ab hier stehen Snapshots, nur die Namen merken
            cfg['snapshots'].append(line[1:-1])
            continue
        m = _KV.match(line)
        if not m or snap:
            continue
        key, value = m.group(1), m.group(2).strip()
        if key == 'description':  # Notiz aus der Weboberfläche, von pct config mit %XX kodiert (z. B. %0A)
            cfg['description'] = unquote(value)
            continue
        cfg['lines'].append([key, value])  # alle Zeilen in Reihenfolge, für die Anzeige (0.5.6)
        if key == 'lxc.mount.entry':  # z. B. „/mnt/daten mnt/daten none bind,create=dir 0 0“ (Weg F)
            f = value.split()
            if len(f) >= 4:
                opts = f[3].split(',')
                cfg['mounts'].append({'key': key, 'source': f[0], 'target': '/' + f[1].lstrip('/'),
                                      'kind': 'bind' if 'bind' in opts or 'rbind' in opts else 'other',
                                      'readonly': 'ro' in opts, 'options': {o: True for o in opts}, 'entry': True})
            continue
        if key == 'lxc.idmap':
            f = value.split()
            if len(f) == 4 and f[0] in ('u', 'g') and all(x.isdigit() for x in f[1:]):
                cfg['idmap'].append({'kind': f[0], 'ct': int(f[1]), 'host': int(f[2]), 'count': int(f[3])})
            continue
        cfg['raw'][key] = value
        if key == 'hostname':
            cfg['hostname'] = value
        elif key == 'unprivileged':
            cfg['unprivileged'] = value == '1'
        elif key == 'onboot':
            cfg['onboot'] = value == '1'
        elif key == 'features':
            _, cfg['features'] = _options(value)
        elif key == 'net0':
            _, o = _options(value)
            cfg['ip'] = o.get('ip', '')
        elif _MP.match(key):
            source, o = _options(value)
            cfg['mounts'].append({'key': key, 'source': source, 'target': o.get('mp', ''),
                                  'kind': 'bind' if source.startswith('/') else 'volume',
                                  'readonly': o.get('ro') == '1', 'options': o})
    cfg['mounts'].sort(key=lambda x: (1, 0) if x.get('entry') else (0, int(x['key'][2:])))  # mpN zuerst, dann lxc.mount.entry
    return cfg


def passwd(text):
    """`getent passwd` → Liste von Benutzern."""
    out = []
    for line in (text or '').splitlines():
        f = line.split(':')
        if len(f) >= 7 and f[2].isdigit() and f[3].isdigit():
            out.append({'name': f[0], 'uid': int(f[2]), 'gid': int(f[3]), 'gecos': f[4], 'home': f[5], 'shell': f[6]})
    return out


def group(text):
    """`getent group` → Liste von Gruppen mit Mitgliedern."""
    out = []
    for line in (text or '').splitlines():
        f = line.split(':')
        if len(f) >= 4 and f[2].isdigit():
            out.append({'name': f[0], 'gid': int(f[2]), 'members': [m for m in f[3].split(',') if m]})
    return out


def stat(text):
    """Ausgabe von `stat -c '%A|%a|%u|%g|%U|%G|%F|%n' …` → {pfad: {...}}. Fehlende Pfade fehlen im Ergebnis."""
    out = {}
    for line in (text or '').splitlines():
        f = line.split('|', 7)
        if len(f) == 8 and f[2].isdigit() and f[3].isdigit():
            out[f[7]] = {'mode': f[0], 'octal': f[1], 'uid': int(f[2]), 'gid': int(f[3]),  # UNKNOWN = ohne Namen
                         'user': '' if f[4] == 'UNKNOWN' else f[4], 'group': '' if f[5] == 'UNKNOWN' else f[5],
                         'type': f[6]}
    return out


def findmnt(text):
    """`findmnt -J -o TARGET,SOURCE,FSTYPE,OPTIONS` → flache Liste aller Mounts."""
    out = []

    def walk(items):
        for fs in items or []:
            out.append({'target': fs.get('target', ''), 'source': fs.get('source', ''),
                        'fstype': fs.get('fstype', ''), 'options': fs.get('options', '')})
            walk(fs.get('children'))
    walk(json.loads(text or '{}').get('filesystems'))
    return out


def subid(text):
    """/etc/subuid bzw. /etc/subgid → Liste {user, start, count}."""
    out = []
    for line in (text or '').splitlines():
        f = line.strip().split(':')
        if len(f) == 3 and f[1].isdigit() and f[2].isdigit():
            out.append({'user': f[0], 'start': int(f[1]), 'count': int(f[2])})
    return out


def testparm(text):
    """Ausgabe von `testparm -s` → {'global': {...}, 'shares': [{name, path, force user, …}]}.
    Schlüssel klein geschrieben wie in smb.conf. Drucker-Abschnitte fallen weg."""
    out, cur = {'global': {}, 'shares': []}, None
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line[0] in '#;':
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1].strip()
            if name.lower() == 'global':
                cur = out['global']
            elif name.lower() in ('printers', 'print$'):
                cur = {}
            else:
                cur = {'name': name}
                out['shares'].append(cur)
            continue
        if '=' in line and cur is not None:
            k, v = line.split('=', 1)
            cur[' '.join(k.lower().split())] = v.strip()
    return out


def mount_opts(options):
    """'rw,uid=1000,gid=1000,file_mode=0755' → {'rw': True, 'uid': '1000', …}"""
    out = {}
    for o in (options or '').split(','):
        if '=' in o:
            k, v = o.split('=', 1)
            out[k] = v
        elif o:
            out[o] = True
    return out


def exports(text):
    """/etc/exports → [{path, clients: [{host, options: {...}}]}]. Fortsetzungszeilen mit \\ werden verbunden."""
    out = []
    for line in (text or '').replace('\\\n', ' ').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('"'):
            path, _, rest = line[1:].partition('"')
        else:
            path, _, rest = line.partition(' ')
        clients = []
        for c in rest.split():
            host, _, opts = c.partition('(')
            clients.append({'host': host or '*', 'options': mount_opts(opts.rstrip(')'))})
        out.append({'path': path, 'clients': clients})
    return out


SECRET_KEYS = ('password', 'pass', 'secret', 'token', 'key', 'encryption')


def storage_cfg(text):
    """/etc/pve/storage.cfg → [{type, id, props}]. Felder, die nach Passwort oder Schlüssel klingen, fallen weg
    (Proxmox legt Passwörter ohnehin unter /etc/pve/priv/ ab, das PermLens nicht lesen darf)."""
    out, cur = [], None
    for line in (text or '').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line[0].isspace() and ':' in line:
            kind, _, sid = line.partition(':')
            cur = {'type': kind.strip(), 'id': sid.strip(), 'props': {}}
            out.append(cur)
        elif cur is not None:
            k, _, v = line.strip().partition(' ')
            if not any(x in k.lower() for x in SECRET_KEYS) or k == 'fingerprint':
                cur['props'][k] = v.strip()
    return out


def getfacl(text):
    """`getfacl -cpn <pfad>` → Einträge wie beim Wächter-Befehl acl: [{tag, id, perm}], nur die Zugriffs-ACL.
    Standard-Einträge (default:…) und Kommentare (#effective:…) werden übergangen."""
    tags = {('user', False): 'user_obj', ('user', True): 'user', ('group', False): 'group_obj',
            ('group', True): 'group', ('mask', False): 'mask', ('other', False): 'other'}
    out = []
    for line in (text or '').splitlines():
        line = line.split('#', 1)[0].strip()
        f = line.split(':')
        if len(f) != 3 or f[0] == 'default':
            continue
        tag = tags.get((f[0], bool(f[1])))
        if tag and re.match(r'^[r-][w-][x-]$', f[2]) and (not f[1] or f[1].isdigit()):
            out.append({'tag': tag, 'id': int(f[1]) if f[1] else None, 'perm': f[2]})
    return out

