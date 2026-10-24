"""Änderungen im Container (Phase 3): Vorschau, Ausführen, Nachprüfen, Protokoll, Rückgängig.

Jede Aktion wird zuerst als Plan berechnet: genauer Befehl, Einstufung mit Begründung, Zustand vorher und nachher,
was sich für die Benutzer des Containers ändert, und die Aktion, die alles wieder zurückdreht. Ausgeführt wird
derselbe Plan noch einmal frisch berechnet (mit frisch gelesenem Zustand), damit zwischen Vorschau und Klick nichts
untergeschoben werden kann. Der Wächter auf dem Host prüft jeden Schreibbefehl ein weiteres Mal (Schalter-Datei,
genaue Form der Argumente, nur eingehängte Ordner und /home, keine symbolischen Verknüpfungen).

Texte für die Oberfläche stehen als Tupel (deutscher Text mit §, Werte …) und werden in der Vorlage übersetzt."""
import json
import re
import secrets
import shlex
from contextlib import closing

from .. import db
from . import access, parse, ssh

NAME = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')  # wie im Wächter
MIN_ID, MAX_ID = 1000, 59999
MAX_OWNER = 60000
RANGE = re.compile(r'^([1-9][0-9]{2,8})(?:-([1-9][0-9]{2,8}))?$')
SYMBOLIC = re.compile(r'^([ugo]+)([+-])([rwx]+)$')
PERM = re.compile(r'^[r-][w-][x-]$')
PATH_OK = re.compile(r'^/[A-Za-z0-9 ._@+,:=~/-]*$')
TIMEOUT = 90

RATINGS = {'harmlos': 'harmlos', 'vorsicht': 'Vorsicht', 'risiko': 'Risiko'}
PATH_ACTIONS = ('besitzer', 'rechte', 'acl-setzen', 'acl-entfernen')


def write_ranges(text):
    """'9001-9006,112' (Antwort des Wächters) → [(9001, 9006), (112, 112)]"""
    out = []
    for item in (text or '').split(','):
        m = RANGE.match(item.strip())
        if m:
            out.append((int(m.group(1)), int(m.group(2) or m.group(1))))
    return out


def write_allowed(text, vmid):
    return any(lo <= int(vmid) <= hi for lo, hi in write_ranges(text))


def _groups(guest):
    return ((guest or {}).get('details') or {}).get('groups') or []


def _users(guest):
    return ((guest or {}).get('details') or {}).get('users') or []


def free_uid(guest, start=MIN_ID):
    used = {u['uid'] for u in _users(guest)}
    uid = start
    while uid in used and uid < MAX_ID:
        uid += 1
    return uid


def free_gid(guest, start=MIN_ID):
    """Kleinste freie Gruppennummer ab start (als Vorschlag im Formular)."""
    used = {g['gid'] for g in _groups(guest)}
    gid = start
    while gid in used and gid < MAX_ID:
        gid += 1
    return gid


def _id(text):
    text = str(text or '').strip()
    return int(text) if text.isdigit() and MIN_ID <= int(text) <= MAX_ID else None


def _owner(text):
    text = str(text or '').strip()
    return int(text) if text.isdigit() and int(text) <= MAX_OWNER else None


def targets(guest):
    """Ordner, in denen PermLens ändern darf: eingehängte Ordner des Containers und /home (wie im Wächter)."""
    out = {'/home'}
    for m in ((guest or {}).get('config') or {}).get('mounts', []):
        t = (m.get('target') or '').rstrip('/')
        if t:
            out.add(t if t.startswith('/') else '/' + t)
    return out


def path_ok(guest, path):
    p = path or ''
    return (bool(PATH_OK.match(p)) and '/../' not in p + '/' and '/./' not in p + '/' and p != '/'
            and any(p == t or p.startswith(t + '/') for t in targets(guest)))


def _uname(guest, uid):
    return next((u['name'] for u in _users(guest) if u['uid'] == uid), '')


def _gname(guest, gid):
    return next((g['name'] for g in _groups(guest) if g['gid'] == gid), '')


def _who(guest, uid, gid):
    """'1000:1000 (alice:media)' – Namen, soweit der Container sie kennt."""
    names = f'{_uname(guest, uid) or "?"}:{_gname(guest, gid) or "?"}'
    return f'{uid}:{gid}' + ('' if names == '?:?' else f' ({names})')


def mode_text(mode):
    """0o2775 → '2775 (rwxrwsr-x)'"""
    s = ''.join(c if mode & b else '-' for c, b in zip('rwxrwxrwx', (256, 128, 64, 32, 16, 8, 4, 2, 1)))
    if mode & 0o2000:
        s = s[:5] + ('s' if mode & 0o010 else 'S') + s[6:]
    if mode & 0o1000:
        s = s[:8] + ('t' if mode & 0o001 else 'T')
    return f'{mode:o} ({s})'


def mode_arg(old, new, folder):
    """Zahl für chmod. Ein Ordner behält setgid bei kurzer Zahl, deshalb zum Entfernen eine führende 0."""
    if folder and old & 0o7000 & ~new:
        return f'0{new:04o}'
    return f'{new:04o}' if new & 0o7000 else f'{new:03o}'


def apply_symbolic(mode, text):
    """'g+w' auf eine Zahl anwenden. None bei ungültiger Angabe."""
    m = SYMBOLIC.match(text or '')
    if not m:
        return None
    bits = 0
    for who in m.group(1):
        shift = {'u': 6, 'g': 3, 'o': 0}[who]
        for c in m.group(3):
            bits |= {'r': 4, 'w': 2, 'x': 1}[c] << shift
    return mode | bits if m.group(2) == '+' else mode & ~bits


# ---------------------------------------------------------------- Zustand eines Pfads im Container
def read_state(host, port, vmid, path):
    """stat (Pfad und Ordner davor) und ACL eines Pfads, frisch aus dem Container."""
    from .scan import stat_live
    stats, r = stat_live(host, port, vmid, path)
    if not r.ok and not stats:
        return {'stat': None, 'stats': {}, 'acl': None,
                'error': ('Keine Antwort. Ist das NAS ausgeschaltet?',) if r.rc == 124 else (ssh.explain(r),)}
    a = ssh.run(host, ['pct', 'exec', str(vmid), '--', 'getfacl', '-cpn', path], port, timeout=20)
    return {'stat': stats.get(path), 'stats': stats, 'acl': parse.getfacl(a.out) if a.ok else None, 'error': None,
            'acl_missing': not a.ok}


def _acl_entry(state, kind, xid):
    tag = 'user' if kind == 'u' else 'group'
    return next((e for e in (state.get('acl') or []) if e['tag'] == tag and e['id'] == xid), None)


def _need_state(state, p):
    """Fehler, wenn der Pfad nicht gelesen werden konnte."""
    if state is None:
        return ('Der Zustand des Ordners konnte nicht gelesen werden.',)
    if state.get('error'):
        return state['error']
    if not state.get('stat'):
        return ('Diesen Pfad gibt es im Container nicht.',)
    return None


# ---------------------------------------------------------------- die einzelnen Aktionen
def _gruppe_anlegen(p, guest, params, state):
    name, gid = str(params.get('name', '')).strip(), _id(params.get('gid'))
    p['params'] = {'name': name, 'gid': str(gid or params.get('gid', '')).strip()}
    p['title'] = ('Gruppe anlegen',)
    if not NAME.match(name):
        return ('Der Gruppenname ist ungültig: Kleinbuchstaben, Ziffern, _ und -, am Anfang ein Buchstabe, höchstens 32 Zeichen.',)
    if gid is None:
        return ('Die Gruppennummer muss zwischen § und § liegen.', MIN_ID, MAX_ID)
    for g in _groups(guest):
        if g['name'] == name:
            return ('Die Gruppe § gibt es schon (Nummer §).', name, g['gid'])
        if g['gid'] == gid:
            return ('Die Nummer § ist schon vergeben (Gruppe §).', gid, g['name'])
    p['cmd'] = ['groupadd', '-g', str(gid), name]
    p['rating'] = 'harmlos'
    p['reason'] = ('Legt nur eine neue, leere Gruppe an. An bestehenden Rechten ändert sich nichts.',)
    p['before'] = [('Es gibt keine Gruppe § und keine Gruppe mit der Nummer §.', name, gid)]
    p['after'] = [('Gruppe § mit der Nummer §, noch ohne Mitglieder.', name, gid)]
    p['undo'] = {'action': 'gruppe-loeschen', 'params': {'name': name}}
    return None


def _gruppe_loeschen(p, guest, params, state):
    name = str(params.get('name', '')).strip()
    p['params'] = {'name': name}
    p['title'] = ('Gruppe löschen',)
    group = next((g for g in _groups(guest) if g['name'] == name), None)
    if not NAME.match(name) or not group:
        return ('Die Gruppe § gibt es in diesem Container nicht.', name)
    if not MIN_ID <= group['gid'] <= MAX_ID:
        return ('Gruppen unter Nummer 1000 sind Systemgruppen. PermLens löscht sie nicht.',)
    primary = [u['name'] for u in _users(guest) if u['gid'] == group['gid']]
    if primary:
        return ('Die Gruppe ist Hauptgruppe von §. Sie lässt sich nicht löschen, solange das so ist.', ', '.join(primary))
    if group['members']:
        return ('Die Gruppe hat noch Mitglieder (§). Erst die Mitglieder entfernen, dann löschen.', ', '.join(group['members']))
    p['cmd'] = ['groupdel', name]
    p['rating'] = 'vorsicht'
    p['reason'] = ('Dateien, die dieser Gruppe gehören, zeigen danach nur noch die Nummer §. Mit „Rückgängig“ entsteht die Gruppe mit derselben Nummer neu, dann passt wieder alles.', group['gid'])
    p['before'] = [('Gruppe § mit der Nummer §, ohne Mitglieder.', name, group['gid'])]
    p['after'] = [('Keine Gruppe § mehr. Die Nummer § ist wieder frei.', name, group['gid'])]
    p['undo'] = {'action': 'gruppe-anlegen', 'params': {'name': name, 'gid': str(group['gid'])}}
    return None


def _path_first(p, guest, params, state, title):
    """Gemeinsamer Anfang der Ordner-Aktionen. Gibt (Pfad, stat, Fehler) zurück."""
    path = str(params.get('path', '')).strip()
    p['params'] = {'path': path}
    p['title'] = title
    p['path'] = path
    if not path_ok(guest, path):
        return path, None, ('Ändern geht nur in eingehängten Ordnern des Containers und unter /home.',)
    err = _need_state(state, p)
    st = (state or {}).get('stat')
    if not err and access.unmapped(st, bool((guest.get('config') or {}).get('unprivileged'))):
        err = ('Der Pfad gehört für diesen Container nobody (Besitzer auf dem Host nicht abgebildet). Dann kann auch root im Container weder Besitzer noch Rechte ändern. Die Lösung liegt auf dem Proxmox-Host, siehe die Empfehlungen der Diagnose.',)
    return path, st, err


def _besitzer(p, guest, params, state):
    path, st, err = _path_first(p, guest, params, state, ('Besitzer ändern',))
    uid, gid = _owner(params.get('uid')), _owner(params.get('gid'))
    p['params'].update(uid=str(params.get('uid', '')).strip(), gid=str(params.get('gid', '')).strip())
    if err:
        return err
    if uid is None or gid is None:
        return ('Besitzer und Gruppe als Nummern angeben (0 bis §).', MAX_OWNER)
    if (st['uid'], st['gid']) == (uid, gid):
        return ('Der Ordner gehört schon §. Es gibt nichts zu ändern.', _who(guest, uid, gid))
    p['cmd'] = ['chown', f'{uid}:{gid}', path]
    p['new_stat'] = {**st, 'uid': uid, 'gid': gid}
    p['rating'] = 'vorsicht'
    p['reason'] = ('Ändert, wem der Ordner gehört. Wer bisher über Besitzer oder Gruppe Zugriff hatte, kann ihn verlieren. Nur dieser eine Pfad, nicht der Inhalt.',)
    p['before'] = [('Besitzer und Gruppe: §', _who(guest, st['uid'], st['gid']))]
    p['after'] = [('Besitzer und Gruppe: §', _who(guest, uid, gid))]
    if _owner(st['uid']) is None or _owner(st['gid']) is None:
        p['rating'] = 'risiko'
        p['reason'] = ('Der bisherige Besitzer (§:§) ist im Container nicht abgebildet. Rückgängig machen kann PermLens das deshalb nicht.', st['uid'], st['gid'])
    else:
        p['undo'] = {'action': 'besitzer', 'params': {'path': path, 'uid': str(st['uid']), 'gid': str(st['gid'])}}
    return None


def _rechte(p, guest, params, state):
    path, st, err = _path_first(p, guest, params, state, ('Rechte ändern',))
    p['params'].update({k: str(params[k]).strip() for k in ('mode', 'add') if params.get(k)})
    if err:
        return err
    old = int(st.get('octal') or '0', 8)
    if params.get('add'):
        new = apply_symbolic(old, str(params['add']).strip())
        if new is None:
            return ('Die Angabe § ist ungültig (Beispiel: g+w).', params['add'])
    else:
        text = str(params.get('mode', '')).strip()
        if not re.match(r'^0?[0-3]?[0-7]{3}$', text):
            return ('Die Rechte als Zahl angeben, z. B. 2775 oder 750. setuid (4…) setzt PermLens nicht.',)
        new = int(text, 8)
    if new & 0o4000:
        return ('setuid (4…) setzt PermLens nicht.',)
    if new == old:
        return ('Die Rechte sind schon §. Es gibt nichts zu ändern.', mode_text(old))
    folder = access.is_dir(st)
    p['cmd'] = ['chmod', mode_arg(old, new, folder), path]
    p['new_stat'] = {**st, 'octal': f'{new:o}'}
    p['rating'] = 'vorsicht'
    p['reason'] = ('Ändert, wer den Ordner lesen, beschreiben oder betreten darf. Nur dieser eine Pfad, nicht der Inhalt.',)
    if new & 0o002:
        p['rating'] = 'risiko'
        p['reason'] = ('Danach darf jeder im Container hier schreiben („andere“ bekommt w).',)
    p['before'] = [('Rechte: §', mode_text(old))]
    p['after'] = [('Rechte: §', mode_text(new))]
    p['undo'] = {'action': 'rechte', 'params': {'path': path, 'mode': mode_arg(new, old, folder)}}
    return None


def _acl_first(p, guest, params, state, title):
    path, st, err = _path_first(p, guest, params, state, title)
    kind, xid = str(params.get('kind', '')).strip(), _owner(params.get('id'))
    p['params'].update(kind=kind, id=str(params.get('id', '')).strip())
    if err:
        return path, st, kind, xid, err
    if state.get('acl_missing'):
        return path, st, kind, xid, ('Im Container fehlt das Paket acl (getfacl/setfacl). Ohne es gehen ACLs nicht.',)
    if kind not in ('u', 'g') or xid is None:
        return path, st, kind, xid, ('Für wen? Benutzer (u) oder Gruppe (g) mit Nummer angeben.',)
    return path, st, kind, xid, None


def _acl_label(guest, kind, xid):
    name = _uname(guest, xid) if kind == 'u' else _gname(guest, xid)
    return ('Benutzer' if kind == 'u' else 'Gruppe') + f' {xid}' + (f' ({name})' if name else '')


def _acl_setzen(p, guest, params, state):
    path, st, kind, xid, err = _acl_first(p, guest, params, state, ('ACL-Eintrag setzen',))
    perm = str(params.get('perm', '')).strip()
    p['params']['perm'] = perm
    if err:
        return err
    if not PERM.match(perm):
        return ('Rechte als drei Zeichen angeben, z. B. rwx, r-x oder r--.',)
    old = _acl_entry(state, kind, xid)
    if old and old['perm'] == perm:
        return ('Diesen Eintrag gibt es schon so. Es gibt nichts zu ändern.',)
    who = _acl_label(guest, kind, xid)
    p['cmd'] = ['setfacl', '-m', f'{kind}:{xid}:{perm}', path]
    acl = [e for e in (state.get('acl') or []) if e is not old]
    acl.append({'tag': 'user' if kind == 'u' else 'group', 'id': xid, 'perm': perm})
    p['new_acl'] = acl
    p['rating'] = 'vorsicht'
    p['reason'] = ('Gibt genau diesem Benutzer bzw. dieser Gruppe eigene Rechte an diesem Pfad, zusätzlich zu Besitzer, Gruppe und „andere“.',)
    p['before'] = [('ACL für §: §', who, old['perm']) if old else ('Kein ACL-Eintrag für §.', who)]
    p['after'] = [('ACL für §: §', who, perm)]
    p['undo'] = ({'action': 'acl-setzen', 'params': {'path': path, 'kind': kind, 'id': str(xid), 'perm': old['perm']}}
                 if old else {'action': 'acl-entfernen', 'params': {'path': path, 'kind': kind, 'id': str(xid)}})
    if not old and not any(e['tag'] in ('user', 'group') for e in state.get('acl') or []):
        p['undo_all'] = True  # Rückgängig wird setfacl -b (siehe _acl_entfernen)
    return None


def _acl_entfernen(p, guest, params, state):
    path, st, kind, xid, err = _acl_first(p, guest, params, state, ('ACL-Eintrag entfernen',))
    if err:
        return err
    old = _acl_entry(state, kind, xid)
    who = _acl_label(guest, kind, xid)
    if not old:
        return ('Es gibt keinen ACL-Eintrag für §.', who)
    p['new_acl'] = [e for e in state['acl'] if e is not old]
    if not any(e['tag'] in ('user', 'group') for e in p['new_acl']):
        # letzter eigener Eintrag: ganz ohne ACL zurück (setfacl -x ließe die Maske stehen)
        p['cmd'] = ['setfacl', '-b', path]
        p['new_acl'] = [e for e in p['new_acl'] if e['tag'] != 'mask']
    else:
        p['cmd'] = ['setfacl', '-x', f'{kind}:{xid}', path]
    p['rating'] = 'vorsicht'
    p['reason'] = ('Nimmt diesem Benutzer bzw. dieser Gruppe die eigenen Rechte an diesem Pfad. Danach gelten für sie nur noch Besitzer, Gruppe und „andere“.',)
    p['before'] = [('ACL für §: §', who, old['perm'])]
    p['after'] = [('Kein ACL-Eintrag für §.', who)]
    p['undo'] = {'action': 'acl-setzen', 'params': {'path': path, 'kind': kind, 'id': str(xid), 'perm': old['perm']}}
    return None


# ---------------------------------------------------------------- Benutzer und Mitgliedschaften (AP 3.5)
def _user(guest, name):
    return next((u for u in _users(guest) if u['name'] == name), None)


def _group(guest, name):
    return next((g for g in _groups(guest) if g['name'] == name), None)


def _member_groups(guest, name):
    return [g['name'] for g in _groups(guest) if name in g['members']]


def _normal_user(guest, name):
    """(Benutzer, Fehler) – nur Benutzer ab Nummer 1000."""
    u = _user(guest, name) if NAME.match(name or '') else None
    if not u:
        return None, ('Den Benutzer § gibt es in diesem Container nicht.', name)
    if not MIN_ID <= u['uid'] <= MAX_ID:
        return None, ('Benutzer unter Nummer 1000 sind Systembenutzer. PermLens ändert sie nicht.',)
    return u, None


def _normal_group(guest, name):
    g = _group(guest, name) if NAME.match(name or '') else None
    if not g:
        return None, ('Die Gruppe § gibt es in diesem Container nicht.', name)
    if not MIN_ID <= g['gid'] <= MAX_ID:
        return None, ('Gruppen unter Nummer 1000 sind Systemgruppen. Dort nimmt PermLens niemanden auf.',)
    return g, None


def _with(guest, users=None, groups=None):
    """Container mit geänderten Benutzern bzw. Gruppen (für die Rechnung „nachher“)."""
    det = dict(guest.get('details') or {})
    if users is not None:
        det['users'] = users
    if groups is not None:
        det['groups'] = groups
    return {**guest, 'details': det}


def _member_effects(guest, after, name):
    """Was ein Benutzer nach einer Änderung an Gruppen in den eingehängten Ordnern lesen/schreiben kann."""
    from .view import diagnose
    u = _user(after, name) or _user(guest, name)
    if not u:
        return []
    out = []
    for m in (guest.get('config') or {}).get('mounts', []):
        path = m.get('target')
        if not path:
            continue
        a, b = diagnose(guest, u['uid'], path), diagnose(after, u['uid'], path)
        if a and b:
            for what in ('read', 'write'):
                if a[what] != b[what]:
                    out.append({'user': f'{name} · {path}', 'uid': u['uid'], 'what': what, 'after': b[what]})
    return out


def _benutzer_anlegen(p, guest, params, state):
    name, uid, gid = str(params.get('name', '')).strip(), _id(params.get('uid')), _id(params.get('gid'))
    p['params'] = {'name': name, 'uid': str(params.get('uid', '')).strip(), 'gid': str(params.get('gid', '')).strip()}
    p['title'] = ('Benutzer anlegen',)
    if not NAME.match(name):
        return ('Der Benutzername ist ungültig: Kleinbuchstaben, Ziffern, _ und -, am Anfang ein Buchstabe, höchstens 32 Zeichen.',)
    if uid is None or gid is None:
        return ('Benutzer- und Gruppennummer müssen zwischen § und § liegen.', MIN_ID, MAX_ID)
    if _user(guest, name):
        return ('Den Benutzer § gibt es schon.', name)
    clash = next((u for u in _users(guest) if u['uid'] == uid), None)
    if clash:
        return ('Die Nummer § hat schon der Benutzer §.', uid, clash['name'])
    group = next((g for g in _groups(guest) if g['gid'] == gid), None)
    if not group:
        return ('Eine Gruppe mit der Nummer § gibt es nicht. Erst unter „Gruppen“ anlegen.', gid)
    p['cmd'] = ['useradd', '-m', '-u', str(uid), '-g', str(gid), name]
    p['rating'] = 'vorsicht'
    p['reason'] = ('Legt einen Benutzer mit Home-Ordner an. Ohne Passwort kann er sich nicht anmelden; ein Passwort setzt PermLens nicht, das tippst du bei Bedarf selbst im Container ein (passwd §).', name)
    p['before'] = [('Es gibt keinen Benutzer § und keinen Benutzer mit der Nummer §.', name, uid)]
    p['after'] = [('Benutzer § mit Nummer §, Hauptgruppe § (§), Home-Ordner /home/§.', name, uid, group['name'], gid, name)]
    p['undo'] = {'action': 'benutzer-loeschen', 'params': {'name': name}}
    return None


def _benutzer_loeschen(p, guest, params, state):
    name = str(params.get('name', '')).strip()
    p['params'] = {'name': name}
    p['title'] = ('Benutzer löschen',)
    u, err = _normal_user(guest, name)
    if err:
        return err
    extra = _member_groups(guest, name)
    if extra:
        return ('§ ist noch in den Gruppen §. Erst dort entfernen, dann löschen (so lässt sich alles genau rückgängig machen).', name, ', '.join(extra))
    p['cmd'] = ['userdel', name]
    p['rating'] = 'risiko'
    p['reason'] = ('Der Benutzer verschwindet. Seine Dateien bleiben und zeigen danach nur noch die Nummer §. Der Home-Ordner bleibt erhalten. Läuft ein Dienst als dieser Benutzer, scheitert das Löschen.', u['uid'])
    p['before'] = [('Benutzer § mit Nummer §, Hauptgruppe §.', name, u['uid'], u['gid'])]
    p['after'] = [('Kein Benutzer § mehr. Die Nummer § ist wieder frei.', name, u['uid'])]
    p['undo'] = {'action': 'benutzer-anlegen', 'params': {'name': name, 'uid': str(u['uid']), 'gid': str(u['gid'])}}
    return None


def _mitglied(p, guest, params, add):
    user, grp = str(params.get('user', '')).strip(), str(params.get('group', '')).strip()
    p['params'] = {'user': user, 'group': grp}
    p['title'] = ('In Gruppe aufnehmen',) if add else ('Aus Gruppe entfernen',)
    u, err = _normal_user(guest, user)
    if err:
        return err
    g, err = _normal_group(guest, grp)
    if err:
        return err
    if add and (user in g['members'] or u['gid'] == g['gid']):
        return ('§ ist schon in der Gruppe §.', user, grp)
    if not add and user not in g['members']:
        return ('§ ist nicht als weiteres Mitglied in der Gruppe § eingetragen.', user, grp)
    groups = [dict(x) for x in _groups(guest)]
    for x in groups:
        if x['name'] == grp:
            x['members'] = x['members'] + [user] if add else [m for m in x['members'] if m != user]
    p['after_guest'] = _with(guest, groups=groups)
    p['cmd'] = ['usermod', '-aG', grp, user] if add else ['gpasswd', '-d', user, grp]
    p['rating'] = 'vorsicht'
    p['reason'] = (('§ darf danach alles, was die Gruppe § darf. Laufende Dienste und angemeldete Sitzungen merken das erst nach einem Neustart bzw. einer neuen Anmeldung.', user, grp) if add else
                   ('§ verliert alles, was nur über die Gruppe § erlaubt war. Laufende Dienste merken das erst nach einem Neustart.', user, grp))
    before, after = _member_groups(guest, user), _member_groups(p['after_guest'], user)
    p['before'] = [('Weitere Gruppen von §: §', user, ', '.join(before) or '–')]
    p['after'] = [('Weitere Gruppen von §: §', user, ', '.join(after) or '–')]
    p['undo'] = {'action': 'mitglied-weg' if add else 'mitglied-hinzu', 'params': {'user': user, 'group': grp}}
    return None


def _mitglied_hinzu(p, guest, params, state):
    return _mitglied(p, guest, params, True)


def _mitglied_weg(p, guest, params, state):
    return _mitglied(p, guest, params, False)


def _hauptgruppe(p, guest, params, state):
    user, gid = str(params.get('user', '')).strip(), _id(params.get('gid'))
    p['params'] = {'user': user, 'gid': str(params.get('gid', '')).strip()}
    p['title'] = ('Hauptgruppe ändern',)
    u, err = _normal_user(guest, user)
    if err:
        return err
    g = next((x for x in _groups(guest) if x['gid'] == gid), None) if gid else None
    if not g:
        return ('Eine Gruppe mit der Nummer § (ab 1000) gibt es nicht.', params.get('gid', ''))
    if u['gid'] == gid:
        return ('§ hat schon die Hauptgruppe §.', user, g['name'])
    users = [dict(x, gid=gid) if x['name'] == user else x for x in _users(guest)]
    p['after_guest'] = _with(guest, users=users)
    p['cmd'] = ['usermod', '-g', str(gid), user]
    p['rating'] = 'vorsicht'
    p['reason'] = ('Neue Dateien von § gehören danach der Gruppe §. Achtung: usermod gibt dabei auch die Dateien im Home-Ordner, die der alten Hauptgruppe gehören, der neuen Gruppe.', user, g['name'])
    p['before'] = [('Hauptgruppe von §: § (§)', user, _gname(guest, u['gid']) or '?', u['gid'])]
    p['after'] = [('Hauptgruppe von §: § (§)', user, g['name'], gid)]
    p['undo'] = {'action': 'hauptgruppe', 'params': {'user': user, 'gid': str(u['gid'])}}
    return None


# ---------------------------------------------------------------- Nummern ändern und rekursiv (AP 3.6 und 3.7)
LONG = 950  # Sekunden; etwas länger als das Zeitlimit des Wächters für lange Befehle (900)
MAX_FILES = 200000
CHMOD_R = re.compile(r'^([ugo]+)([+-])([rwxX]+)$')
RECURSIVE = ('besitzer-r', 'rechte-r', 'acl-r')


def chmod_r_ok(text):
    """Wie im Wächter: oktal ohne setuid oder symbolisch ohne s (setgid für einen Ordner geht einzeln)."""
    if re.match(r'^0?[0-3]?[0-7]{3}$', text or ''):
        return True
    parts = (text or '').split(',')
    return 0 < len(parts) <= 6 and all(CHMOD_R.match(x) for x in parts)


def count(host, port, vmid, path, kind='', num=''):
    """Anzahl Dateien und Ordner unter path (optional nur die mit Besitzer bzw. Gruppe num). None = Fehler."""
    args = ['find', path, '-xdev'] + ([f'-{kind}', str(num)] if kind else []) + ['-printf', '.']
    r = ssh.run(host, ['pct', 'exec', str(vmid), '--'] + args, port, timeout=LONG)
    return len(r.out.strip()) if r.rc in (0, 1) and r.out is not None and (r.ok or r.out) else None


def backup(host, port, vmid, path):
    """Besitzer, Rechte und ACLs aller Dateien unter path (getfacl -R). (Text, Fehler)"""
    r = ssh.run(host, ['pct', 'exec', str(vmid), '--', 'getfacl', '-R', '-p', '-n', '-P', path], port, timeout=LONG)
    if not r.out.strip():
        return None, (r.err.replace('permlens-guard: ', 'Wächter: ') if r.rc == ssh.DENIED else ssh.explain(r))
    return r.out, None


def read_extra(host, port, vmid, action, params, guest):
    """Zusätzliche Zahlen für die Vorschau: wie viele Dateien betroffen sind."""
    out = {}
    if action in RECURSIVE and path_ok(guest, params.get('path', '')):
        out['count'] = count(host, port, vmid, params['path'])
    elif action == 'umnummerieren' and path_ok(guest, params.get('path', '')):
        kind = 'user' if params.get('kind') == 'u' else 'group'
        out['old'] = count(host, port, vmid, params['path'], kind, params.get('old', '')) if _owner(params.get('old')) is not None else None
        out['new'] = count(host, port, vmid, params['path'], kind, params.get('new', '')) if _owner(params.get('new')) is not None else None
    elif action in ('uid-aendern', 'gid-aendern'):
        kind = 'user' if action == 'uid-aendern' else 'group'
        item = (_user(guest, params.get('user', '')) or {}).get('uid') if kind == 'user' else \
            (_group(guest, params.get('group', '')) or {}).get('gid')
        if item is not None:
            out['mounts'] = [(t, count(host, port, vmid, t, kind, item)) for t in sorted(targets(guest)) if t != '/home'
                             and t in ((guest.get('details') or {}).get('stat') or {})]
    return out


def _rec_first(p, guest, params, state, title):
    path, st, err = _path_first(p, guest, params, state, title)
    n = (state or {}).get('count')
    if not err and n is None:
        err = ('Die Dateien unter § konnten nicht gezählt werden.', path)
    if not err and n > MAX_FILES:
        err = ('Unter § liegen § Dateien. Rekursiv ändert PermLens höchstens § auf einmal; bitte einen Unterordner wählen.', path, n, MAX_FILES)
    if not err:
        p['info'] = [('Betrifft § Dateien und Ordner unter § (ohne andere Dateisysteme darunter, symbolische Verknüpfungen werden nicht verfolgt).', n, path),
                     ('Vorher sichert PermLens Besitzer, Rechte und ACLs aller dieser Dateien (getfacl -R). „Rückgängig“ spielt genau diese Sicherung zurück.',)]
        p['rating'] = 'risiko'
        p['undo'] = {'action': 'wiederherstellen', 'params': {'path': path}}
    return path, st, err


def _besitzer_r(p, guest, params, state):
    path, st, err = _rec_first(p, guest, params, state, ('Besitzer ändern (ganzer Ordner)',))
    uid, gid = _owner(params.get('uid')), _owner(params.get('gid'))
    p['params'].update(uid=str(params.get('uid', '')).strip(), gid=str(params.get('gid', '')).strip())
    if err:
        return err
    if uid is None or gid is None:
        return ('Besitzer und Gruppe als Nummern angeben (0 bis §).', MAX_OWNER)
    p['cmd'] = ['chown', '-R', '-h', f'{uid}:{gid}', path]
    p['new_stat'] = {**st, 'uid': uid, 'gid': gid}
    p['reason'] = ('Alle Dateien und Ordner darunter gehören danach §.', _who(guest, uid, gid))
    p['before'] = [('Besitzer und Gruppe des Ordners: § (darunter evtl. andere)', _who(guest, st['uid'], st['gid']))]
    p['after'] = [('Alles darunter: §', _who(guest, uid, gid))]
    return None


def _rechte_r(p, guest, params, state):
    path, st, err = _rec_first(p, guest, params, state, ('Rechte ändern (ganzer Ordner)',))
    mode = str(params.get('mode', '')).strip()
    p['params']['mode'] = mode
    if err:
        return err
    if not chmod_r_ok(mode):
        return ('Rechte als Zahl (z. B. 2775) oder wie g+rwX,o-rwx angeben. X gibt x nur Ordnern. setuid und setgid setzt PermLens rekursiv nicht; setgid für einen Ordner geht einzeln.',)
    old = int(st.get('octal') or '0', 8)
    new = int(mode, 8) if mode[0].isdigit() else old
    if not mode[0].isdigit():
        for part in mode.split(','):
            m = CHMOD_R.match(part)
            new = apply_symbolic(new, m.group(1) + m.group(2) + m.group(3).replace('X', 'x'))
    p['cmd'] = ['chmod', '-R', mode, path]
    p['new_stat'] = {**st, 'octal': f'{new:o}'}
    p['reason'] = ('Ändert die Rechte aller Dateien und Ordner darunter. Mit X bekommen nur Ordner (und schon ausführbare Dateien) das Recht x.',)
    p['before'] = [('Rechte des Ordners: § (darunter evtl. andere)', mode_text(old))]
    p['after'] = [('Rechte des Ordners: §, darunter entsprechend §', mode_text(new), mode)]
    return None


def _acl_r(p, guest, params, state):
    path, st, err = _rec_first(p, guest, params, state, ('ACL-Eintrag setzen (ganzer Ordner)',))
    kind, xid, perm = str(params.get('kind', '')).strip(), _owner(params.get('id')), str(params.get('perm', '')).strip()
    default = str(params.get('default', '')).strip() == '1'
    p['params'].update(kind=kind, id=str(params.get('id', '')).strip(), perm=perm, default='1' if default else '')
    if err:
        return err
    if state.get('acl_missing'):
        return ('Im Container fehlt das Paket acl (getfacl/setfacl). Ohne es gehen ACLs nicht.',)
    if kind not in ('u', 'g') or xid is None or not PERM.match(perm):
        return ('Für wen? Benutzer (u) oder Gruppe (g) mit Nummer und Rechten wie rwx angeben.',)
    who = _acl_label(guest, kind, xid)
    p['cmd'] = ['setfacl', '-R'] + (['-d'] if default else []) + ['-m', f'{kind}:{xid}:{perm}', path]
    if not default:
        acl = [e for e in (state.get('acl') or []) if not (e['tag'] == ('user' if kind == 'u' else 'group') and e['id'] == xid)]
        p['new_acl'] = acl + [{'tag': 'user' if kind == 'u' else 'group', 'id': xid, 'perm': perm}]
    p['reason'] = (('Neue Dateien und Ordner darunter bekommen für § automatisch die Rechte § (Standard-ACL). Bestehende Dateien ändern sich nicht.', who, perm) if default
                   else ('Gibt § an allen Dateien und Ordnern darunter die Rechte §.', who, perm))
    p['before'] = [('ACL wie bisher (in der Sicherung festgehalten)',)]
    p['after'] = [('§ für §, überall darunter', ('Standard-ACL' if default else 'ACL'), who)]
    return None


def _wiederherstellen(p, guest, params, state):
    path = str(params.get('path', '')).strip()
    nr = str(params.get('nr', '')).strip()
    p['params'] = {'path': path, 'nr': nr}
    p['path'] = path
    p['title'] = ('Sicherung zurückspielen',)
    if not path_ok(guest, path):
        return ('Ändern geht nur in eingehängten Ordnern des Containers und unter /home.',)
    e = entry(int(nr)) if nr.isdigit() else None
    if not e or not e.get('backup'):
        return ('Zu dieser Änderung gibt es keine Sicherung.',)
    files = e['backup'].count('\n# file: ') + (1 if e['backup'].startswith('# file: ') else 0)
    p['cmd'] = ['setfacl', '--physical', f'--restore=<Sicherung von Nr. {nr}>']
    p['rating'] = 'vorsicht'
    p['reason'] = ('Stellt Besitzer, Rechte und ACLs von § Dateien und Ordnern unter § so her, wie sie vor Änderung Nr. § waren. Dateien, die seitdem neu dazugekommen sind, bleiben, wie sie sind.', files, path, nr)
    p['before'] = [('Zustand nach Änderung Nr. §', nr)]
    p['after'] = [('Zustand vor Änderung Nr. § (aus der Sicherung)', nr)]
    p['info'] = [('Der Wächter prüft, dass jeder Pfad in der Sicherung unter § liegt, und lehnt setuid ab.', path)]
    return None


def _uid_aendern(p, guest, params, state):
    user, new = str(params.get('user', '')).strip(), _id(params.get('uid'))
    p['params'] = {'user': user, 'uid': str(params.get('uid', '')).strip()}
    p['title'] = ('Benutzernummer (UID) ändern',)
    u, err = _normal_user(guest, user)
    if err:
        return err
    if new is None:
        return ('Die neue Nummer muss zwischen § und § liegen.', MIN_ID, MAX_ID)
    clash = next((x for x in _users(guest) if x['uid'] == new), None)
    if clash:
        return ('Die Nummer § hat schon der Benutzer §.', new, clash['name'])
    p['cmd'] = ['usermod', '-u', str(new), user]
    p['rating'] = 'risiko'
    p['reason'] = ('usermod gibt die Dateien im Home-Ordner von § gleich mit der neuen Nummer. Alle anderen Dateien, z. B. in eingehängten Ordnern, gehören danach der alten Nummer § und damit niemandem mehr. Die zieht „Dateien umnummerieren“ als zweiter Schritt nach. Läuft ein Prozess als §, scheitert usermod.', user, u['uid'], user)
    p['before'] = [('§ hat die Nummer §.', user, u['uid'])]
    p['after'] = [('§ hat die Nummer §.', user, new)]
    p['info'] = [('In § gehören § Dateien der Nummer §.', t, n if n is not None else '?', u['uid'])
                 for t, n in (state or {}).get('mounts', [])]
    p['undo'] = {'action': 'uid-aendern', 'params': {'user': user, 'uid': str(u['uid'])}}
    return None


def _gid_aendern(p, guest, params, state):
    grp, new = str(params.get('group', '')).strip(), _id(params.get('gid'))
    p['params'] = {'group': grp, 'gid': str(params.get('gid', '')).strip()}
    p['title'] = ('Gruppennummer (GID) ändern',)
    g, err = _normal_group(guest, grp)
    if err:
        return err
    if new is None:
        return ('Die neue Nummer muss zwischen § und § liegen.', MIN_ID, MAX_ID)
    clash = next((x for x in _groups(guest) if x['gid'] == new), None)
    if clash:
        return ('Die Nummer § ist schon vergeben (Gruppe §).', new, clash['name'])
    p['cmd'] = ['groupmod', '-g', str(new), grp]
    p['rating'] = 'risiko'
    p['reason'] = ('Benutzer mit dieser Hauptgruppe bekommen die neue Nummer automatisch. Dateien behalten die alte Nummer § und gehören damit keiner Gruppe mehr; das zieht „Dateien umnummerieren“ als zweiter Schritt nach.', g['gid'])
    p['before'] = [('Gruppe § hat die Nummer §.', grp, g['gid'])]
    p['after'] = [('Gruppe § hat die Nummer §.', grp, new)]
    p['info'] = [('In § gehören § Dateien der Gruppennummer §.', t, n if n is not None else '?', g['gid'])
                 for t, n in (state or {}).get('mounts', [])]
    p['undo'] = {'action': 'gid-aendern', 'params': {'group': grp, 'gid': str(g['gid'])}}
    return None


def _umnummerieren(p, guest, params, state):
    path = str(params.get('path', '')).strip()
    kind, old, new = str(params.get('kind', '')).strip(), _owner(params.get('old')), _owner(params.get('new'))
    p['params'] = {'path': path, 'kind': kind, 'old': str(params.get('old', '')).strip(), 'new': str(params.get('new', '')).strip()}
    p['path'] = path
    p['title'] = ('Dateien umnummerieren',)
    if not path_ok(guest, path):
        return ('Ändern geht nur in eingehängten Ordnern des Containers und unter /home.',)
    if kind not in ('u', 'g') or old is None or new is None or old == new:
        return ('Besitzer (u) oder Gruppe (g) und zwei verschiedene Nummern angeben.',)
    n_old, n_new = (state or {}).get('old'), (state or {}).get('new')
    if n_old is None or n_new is None:
        return ('Die Dateien unter § konnten nicht gezählt werden.', path)
    if not n_old:
        return ('Unter § gehört keine Datei der Nummer §. Es gibt nichts zu ändern.', path, old)
    if n_new:
        return ('Unter § gehören schon § Dateien der Nummer §. Dann ließe sich das nicht sauber rückgängig machen; PermLens macht es deshalb nicht.', path, n_new, new)
    what = 'user' if kind == 'u' else 'group'
    p['cmd'] = ['find', path, '-xdev', f'-{what}', str(old), '-exec', 'chown' if kind == 'u' else 'chgrp', '-h', str(new), '{}', '+']
    p['rating'] = 'risiko'
    p['reason'] = ('Alle § Dateien und Ordner unter §, die der Nummer § gehören, gehören danach der Nummer §. Andere Dateien bleiben unverändert.', n_old, path, old, new)
    p['before'] = [('§ Dateien gehören der Nummer §, keine der Nummer §.', n_old, old, new)]
    p['after'] = [('Die § Dateien gehören der Nummer §.', n_old, new)]
    p['undo'] = {'action': 'umnummerieren', 'params': {'path': path, 'kind': kind, 'old': str(new), 'new': str(old)}}
    return None


ACTIONS = {'gruppe-anlegen': _gruppe_anlegen, 'gruppe-loeschen': _gruppe_loeschen, 'besitzer': _besitzer,
           'rechte': _rechte, 'acl-setzen': _acl_setzen, 'acl-entfernen': _acl_entfernen,
           'benutzer-anlegen': _benutzer_anlegen, 'benutzer-loeschen': _benutzer_loeschen,
           'mitglied-hinzu': _mitglied_hinzu, 'mitglied-weg': _mitglied_weg, 'hauptgruppe': _hauptgruppe,
           'besitzer-r': _besitzer_r, 'rechte-r': _rechte_r, 'acl-r': _acl_r, 'wiederherstellen': _wiederherstellen,
           'uid-aendern': _uid_aendern, 'gid-aendern': _gid_aendern, 'umnummerieren': _umnummerieren}
USER_ACTIONS = ('benutzer-anlegen', 'benutzer-loeschen', 'mitglied-hinzu', 'mitglied-weg', 'hauptgruppe',
                'uid-aendern', 'gid-aendern')
PATH_ACTIONS = PATH_ACTIONS + RECURSIVE + ('wiederherstellen', 'umnummerieren')


def cmd_of(action, params):
    """Befehl einer (Rückgängig-)Aktion, ohne erneute Prüfung – nur zum Anzeigen in der Vorschau."""
    q = params
    return {'gruppe-anlegen': lambda: ['groupadd', '-g', q.get('gid', ''), q.get('name', '')],
            'gruppe-loeschen': lambda: ['groupdel', q.get('name', '')],
            'besitzer': lambda: ['chown', f'{q.get("uid")}:{q.get("gid")}', q.get('path', '')],
            'rechte': lambda: ['chmod', q.get('mode', ''), q.get('path', '')],
            'acl-setzen': lambda: ['setfacl', '-m', f'{q.get("kind")}:{q.get("id")}:{q.get("perm")}', q.get('path', '')],
            'acl-entfernen': lambda: ['setfacl', '-x', f'{q.get("kind")}:{q.get("id")}', q.get('path', '')],
            'benutzer-anlegen': lambda: ['useradd', '-m', '-u', q.get('uid', ''), '-g', q.get('gid', ''), q.get('name', '')],
            'benutzer-loeschen': lambda: ['userdel', q.get('name', '')],
            'mitglied-hinzu': lambda: ['usermod', '-aG', q.get('group', ''), q.get('user', '')],
            'mitglied-weg': lambda: ['gpasswd', '-d', q.get('user', ''), q.get('group', '')],
            'hauptgruppe': lambda: ['usermod', '-g', q.get('gid', ''), q.get('user', '')],
            'uid-aendern': lambda: ['usermod', '-u', q.get('uid', ''), q.get('user', '')],
            'gid-aendern': lambda: ['groupmod', '-g', q.get('gid', ''), q.get('group', '')],
            'umnummerieren': lambda: ['find', q.get('path', ''), '-xdev', '-user' if q.get('kind') == 'u' else '-group',
                                      q.get('old', ''), '-exec', 'chown' if q.get('kind') == 'u' else 'chgrp', '-h',
                                      q.get('new', ''), '{}', '+'],
            'wiederherstellen': lambda: ['setfacl', '--physical', '--restore=<Sicherung>'],
            }.get(action, list)()


def effects(guest, p, state):
    """Wer im Container durch die Änderung Lesen oder Schreiben gewinnt oder verliert (Rechte-Rechner aus Phase 2)."""
    from .view import diagnose
    if not (p.get('new_stat') or p.get('new_acl') is not None) or not state or not state.get('stat'):
        return []
    path, acl = p['path'], state.get('acl')
    after = {**state['stats'], path: p.get('new_stat') or state['stat']}
    out = []
    for u in _users(guest):
        if u['uid'] != 0 and not MIN_ID <= u['uid'] <= MAX_ID:
            continue
        a = diagnose(guest, u['uid'], path, state['stats'], acl)
        b = diagnose(guest, u['uid'], path, after, p['new_acl'] if p.get('new_acl') is not None else acl)
        if a and b:
            for what in ('read', 'write'):
                if a[what] != b[what]:
                    out.append({'user': u['name'], 'uid': u['uid'], 'what': what, 'after': b[what]})
    return out


def plan(action, guest, params, write_ids, state=None):
    """Vorschau einer Aktion. 'error' ist leer oder ein Tupel mit dem Grund, warum sie nicht geht.
    state: frisch gelesener Zustand des Pfads (read_state) für die Ordner-Aktionen."""
    p = {'action': action, 'vmid': (guest or {}).get('vmid'), 'ct_name': (guest or {}).get('name', ''),
         'params': {}, 'title': ('Änderung',), 'cmd': [], 'shell': '', 'pct': '', 'rating': '', 'reason': None,
         'before': [], 'after': [], 'undo': None, 'undo_shell': '', 'error': None, 'effects': [], 'path': '',
         'info': []}
    if action not in ACTIONS:
        p['error'] = ('Diese Änderung kennt PermLens nicht.',)
        return p
    if not guest:
        p['error'] = ('Diesen Container gibt es nicht.',)
        return p
    p['error'] = ACTIONS[action](p, guest, params or {}, state)
    if not p['error'] and not (guest.get('status') == 'running' and guest.get('details')):
        p['error'] = ('Der Container läuft nicht. Änderungen gehen nur in laufenden Containern.',)
    if p['error']:
        p['cmd'] = []
    if p['cmd']:
        p['shell'] = shlex.join(p['cmd'])
        p['pct'] = shlex.join(['pct', 'exec', str(p['vmid']), '--'] + p['cmd'])
        if p['undo']:
            undo_cmd = (['setfacl', '-b', p['path']] if p.get('undo_all')
                        else ['setfacl', '--physical', '--restore=<Sicherung>'] if p['undo']['action'] == 'wiederherstellen'
                        else cmd_of(p['undo']['action'], p['undo']['params']))
            p['undo_shell'] = shlex.join(undo_cmd)
        p['effects'] = (_member_effects(guest, p['after_guest'], p['params']['user']) if p.get('after_guest')
                        else effects(guest, p, state))
    p['allowed'] = write_allowed(write_ids, p['vmid']) if p['vmid'] else False
    return p


def _verify(p, host, port):
    """Nach dem Ausführen nachlesen: Ist der Zustand so, wie die Vorschau gesagt hat?"""
    vmid, q = str(p['vmid']), p['params']
    if p['action'] in ('gruppe-anlegen', 'gruppe-loeschen'):
        r = ssh.run(host, ['pct', 'exec', vmid, '--', 'getent', 'group'], port, timeout=30)
        names = {g['name']: g for g in parse.group(r.out)} if r.ok else None
        if names is None:
            return False
        if p['action'] == 'gruppe-anlegen':
            return q['name'] in names and str(names[q['name']]['gid']) == q['gid']
        return q['name'] not in names
    if p['action'] in USER_ACTIONS:
        pw = ssh.run(host, ['pct', 'exec', vmid, '--', 'getent', 'passwd'], port, timeout=30)
        gr = ssh.run(host, ['pct', 'exec', vmid, '--', 'getent', 'group'], port, timeout=30)
        if not (pw.ok and gr.ok):
            return False
        users = {u['name']: u for u in parse.passwd(pw.out)}
        groups = {g['name']: g for g in parse.group(gr.out)}
        if p['action'] == 'benutzer-anlegen':
            u = users.get(q['name'])
            return bool(u) and str(u['uid']) == q['uid'] and str(u['gid']) == q['gid']
        if p['action'] == 'benutzer-loeschen':
            return q['name'] not in users
        if p['action'] == 'hauptgruppe':
            return str((users.get(q['user']) or {}).get('gid')) == q['gid']
        if p['action'] == 'uid-aendern':
            return str((users.get(q['user']) or {}).get('uid')) == q['uid']
        if p['action'] == 'gid-aendern':
            return str((groups.get(q['group']) or {}).get('gid')) == q['gid']
        members = (groups.get(q['group']) or {}).get('members', [])
        return (q['user'] in members) == (p['action'] == 'mitglied-hinzu')
    if p['action'] == 'umnummerieren':
        return count(host, port, vmid, q['path'], 'user' if q['kind'] == 'u' else 'group', q['old']) == 0
    if p['action'] == 'wiederherstellen':
        now, _ = backup(host, port, vmid, q['path'])
        old = entry(int(q['nr']))['backup']
        files = lambda t: {b for b in t.split('\n\n') if b.strip()}  # noqa: E731
        return now is not None and files(old) <= files(now)  # neue Dateien dürfen dazugekommen sein
    state = read_state(host, port, vmid, q['path'])
    st = state.get('stat')
    if not st:
        return False
    if p['action'] == 'besitzer':
        return (st['uid'], st['gid']) == (p['new_stat']['uid'], p['new_stat']['gid'])
    if p['action'] in ('rechte', 'rechte-r'):
        return int(st['octal'], 8) == int(p['new_stat']['octal'], 8)
    if p['action'] == 'besitzer-r':
        return (st['uid'], st['gid']) == (p['new_stat']['uid'], p['new_stat']['gid'])
    if p['action'] == 'acl-r':
        if q.get('default'):
            return True  # Standard-ACL: getfacl -cpn zeigt sie nicht in der Zugriffs-ACL
        e = _acl_entry(state, q['kind'], int(q['id']))
        return e is not None and e['perm'] == q['perm']
    kind, xid = q['kind'], int(q['id'])
    e = _acl_entry(state, kind, xid)
    return (e is not None and e['perm'] == q['perm']) if p['action'] == 'acl-setzen' else e is None


# ---------------------------------------------------------------- Ausführen und Protokoll
def execute(p, host, port, client='', undo_of=None):
    """Plan ausführen, nachprüfen und protokollieren. Gibt die Nummer des Protokolleintrags zurück."""
    vmid = str(p['vmid'])
    saved = None
    if p['action'] in RECURSIVE:
        saved, why = backup(host, port, vmid, p['path'])
        if saved is None:
            r = ssh.Result(1, '', 'Die Sicherung vor der Änderung hat nicht geklappt, deshalb wurde nichts geändert: ' + why)
    if p['action'] in RECURSIVE and saved is None:
        pass
    elif p['action'] == 'wiederherstellen':
        r = ssh.run(host, ['pct', 'exec', vmid, '--', 'permlens-restore', p['path']], port, timeout=LONG,
                    data=entry(int(p['params']['nr']))['backup'])
    else:
        long = p['action'] in RECURSIVE or p['action'] == 'umnummerieren'
        r = ssh.run(host, ['pct', 'exec', vmid, '--'] + p['cmd'], port, timeout=LONG if long else TIMEOUT)
    if r.ok:
        verified = _verify(p, host, port)
        result = 'ok' if verified else 'abweichung'
        detail = '' if verified else 'Der Befehl lief durch, aber beim Nachlesen sieht der Container anders aus als erwartet.'
    else:
        result = 'fehler'
        detail = r.err.replace('permlens-guard: ', 'Wächter: ') if r.rc == ssh.DENIED else ssh.explain(r)
        saved = None  # nichts geändert: keine Sicherung aufheben, kein Rückgängig
    with closing(db.connect()) as c, c:
        cur = c.execute('INSERT INTO changes (ts, client, host, vmid, ct_name, action, params, shell, rating, result,'
                        ' detail, undo, undo_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (db.now(), client, host, int(vmid), p['ct_name'], p['action'], json.dumps(p['params']),
                         p['shell'], p['rating'], result, detail, json.dumps(p['undo']) if p['undo'] else None,
                         undo_of))
        cid = cur.lastrowid
        if saved is not None:
            undo = {'action': 'wiederherstellen', 'params': {'path': p['path'], 'nr': str(cid)}}
            c.execute('UPDATE changes SET backup = ?, undo = ? WHERE id = ?', (saved, json.dumps(undo), cid))
        if undo_of and result == 'ok':
            c.execute('UPDATE changes SET undone_by = ? WHERE id = ?', (cid, undo_of))
    db.audit('aenderung', target=f'CT {vmid}', result=result, client=client, befehl=p['shell'], nr=cid)
    return cid


def entries(limit=200):
    with closing(db.connect()) as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM changes ORDER BY id DESC LIMIT ?', (limit,))]
    for r in rows:
        r['undo'] = json.loads(r['undo']) if r['undo'] else None
        r['params'] = json.loads(r['params'] or '{}')
    return rows


def entry(cid):
    with closing(db.connect()) as c:
        row = c.execute('SELECT id FROM changes WHERE id = ?', (cid,)).fetchone()
    return next((r for r in entries(100000) if r['id'] == cid), None) if row else None


# ---------------------------------------------------------------- echter Schreibtest (AP 3.4)
def write_test(host, port, vmid, user, gids, folder):
    """Als Benutzer eine leere Testdatei im Ordner anlegen und sofort wieder löschen.
    Gibt {'ok': True/False/None, 'error': Text oder None, 'left': Pfad, falls die Datei nicht weg ist} zurück."""
    groups = '--groups=' + ','.join(str(x) for x in sorted({user['gid'], *gids})) if gids else '--clear-groups'
    sp = ['setpriv', f'--reuid={user["uid"]}', f'--regid={user["gid"]}', groups, '--']
    name = f'{folder.rstrip("/")}/.permlens-schreibtest-{secrets.token_hex(6)}'
    base = ['pct', 'exec', str(vmid), '--']
    r = ssh.run(host, base + sp + ['touch', name], port, timeout=30)
    out = {'ok': None, 'error': None, 'left': '', 'file': name}
    if r.rc == ssh.DENIED:
        out['error'] = (r.err.replace('permlens-guard: ', 'Wächter: '),)
        return out
    if r.rc == 124:
        out['error'] = ('Keine Antwort. Ist das NAS ausgeschaltet?',)
        return out
    out['ok'] = r.ok
    out['detail'] = r.err.strip()
    if r.ok:  # aufräumen: erst als derselbe Benutzer, notfalls als root im Container
        if not ssh.run(host, base + sp + ['rm', '-f', name], port, timeout=30).ok:
            if not ssh.run(host, base + ['rm', '-f', name], port, timeout=30).ok:
                out['left'] = name
    return out
