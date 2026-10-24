"""Daten eines Containers für die Anzeige aufbereiten (Benutzer, Mapping, Mounts)."""
import re

from . import access, docker, explain
from . import mapping as M
from .parse import mount_opts as parse_opts
from .scan import mapping as mapping_kind, parents, status

SYSTEM_MAX = 999  # UIDs bis hier sind meist Systembenutzer (außer root)


def _names(entries, key):
    return {e[key]: e['name'] for e in entries or []}


PERSON_MAX = 59999  # Debian vergibt ab 60000 wieder Systemnummern (z. B. ceph 64045)


def is_person(uid):
    """Normale Benutzer (keine Systembenutzer, nicht root, nicht nobody)."""
    return SYSTEM_MAX < uid <= PERSON_MAX


def names_by_host_id(scan):
    """Host-Nummer → [(wo, Name)] für Benutzer auf dem Host und in allen Containern mit Benutzerliste."""
    hi = (scan or {}).get('host_info') or {}
    out = {}
    for u in hi.get('passwd') or []:
        out.setdefault(u['uid'], []).append(('Host', u['name']))
    for g in (scan or {}).get('guests', []):
        if g['type'] != 'lxc' or not g.get('config'):
            continue
        ur = M.ranges(g['config'], 'u')
        for u in (g.get('details') or {}).get('users', []):
            h = M.to_host(ur, u['uid'])
            if h is not None:
                out.setdefault(h, []).append((str(g['vmid']), u['name']))
    return out


def nameless(scan, guest):
    """Nummern, denen eingehängte Ordner gehören, die im Container aber keinen Benutzer haben (z. B. Docker-Dienste).
    Liste {uid, host_uid, paths, elsewhere}."""
    cfg, det = guest.get('config') or {}, guest.get('details') or {}
    if not det.get('users'):
        return []
    known = {u['uid'] for u in det['users']}
    ur = M.ranges(cfg, 'u')
    stats = det.get('stat') or {}
    owners = {}
    for m in cfg.get('mounts', []):
        st = stats.get(m['target'])
        if not st and m.get('host_stat'):
            ct = M.to_ct(ur, m['host_stat']['uid'])
            st = {'uid': M.NOBODY if ct is None else ct}
        if st and st['uid'] not in known and st['uid'] != M.NOBODY:
            owners.setdefault(st['uid'], []).append(m['target'])
    names = names_by_host_id(scan)
    out = []
    for uid, paths in sorted(owners.items()):
        h = M.to_host(ur, uid)
        out.append({'uid': uid, 'host_uid': h, 'paths': paths,
                    'elsewhere': [x for x in names.get(h, []) if x[0] != str(guest['vmid'])] if h is not None else []})
    return out


def people(scan):
    """Seite „Benutzer“: je Name die Nummern überall, je Host-Nummer die Namen und Ordner."""
    hi = (scan or {}).get('host_info') or {}
    by_name = {}
    for u in hi.get('passwd') or []:
        if is_person(u['uid']):
            by_name.setdefault(u['name'], []).append({'where': 'Host', 'vmid': None, 'uid': u['uid'], 'host_uid': u['uid']})
    guests = [g for g in (scan or {}).get('guests', []) if g['type'] == 'lxc' and g.get('config')]
    for g in guests:
        ur = M.ranges(g['config'], 'u')
        for u in (g.get('details') or {}).get('users', []):
            if is_person(u['uid']):
                by_name.setdefault(u['name'], []).append({'where': g['name'], 'vmid': g['vmid'], 'uid': u['uid'],
                                                          'host_uid': M.to_host(ur, u['uid']),
                                                          'mapping': mapping_kind(g['config'])})
    names = []
    for name, rows in sorted(by_name.items()):
        hosts = {r['host_uid'] for r in rows}
        names.append({'name': name, 'rows': rows, 'differs': len(hosts) > 1})
    names.sort(key=lambda n: (not n['differs'], n['name']))

    owned = {}  # Host-Nummer → Quellen, die ihr gehören
    for g in guests:
        for m in g['config'].get('mounts', []):
            hs = m.get('host_stat')
            if m['kind'] == 'bind' and hs:
                owned.setdefault(hs['uid'], set()).add(m['source'])
    by_id = names_by_host_id(scan)
    numbers = []
    for h in sorted(set(owned) | {r['host_uid'] for n in names for r in n['rows'] if r['host_uid'] is not None}):
        if not (is_person(h) or h in owned) or h == M.NOBODY:
            continue
        who = by_id.get(h, [])
        numbers.append({'host_uid': h, 'names': who, 'sources': sorted(owned.get(h, ())),
                        'differs': len({n for _, n in who}) > 1})
    return {'names': names, 'numbers': numbers}


def accounts(guest):
    """Für die Übersicht: angelegte Benutzer und Gruppen eines Containers (ohne root und Systembenutzer).
    Gruppen, die nur die eigene Gruppe eines Benutzers sind (gleicher Name), fallen weg. None = nicht lesbar."""
    det = guest.get('details') or {}
    if not det.get('users'):
        return None
    users = sorted((u for u in det['users'] if is_person(u['uid'])), key=lambda u: u['uid'])
    own = {(u['name'], u['gid']) for u in users}
    groups = sorted((g for g in det.get('groups', []) if is_person(g['gid']) and (g['name'], g['gid']) not in own),
                    key=lambda g: g['gid'])
    return {'users': [{'name': u['name'], 'uid': u['uid']} for u in users],
            'groups': [{'name': g['name'], 'gid': g['gid'], 'members': g['members']} for g in groups]}


def find(scan, vmid):
    for g in (scan or {}).get('guests', []):
        if g['vmid'] == vmid and g['type'] == 'lxc':
            return g
    return None


def container(scan, guest):
    cfg = guest.get('config') or {}
    det = guest.get('details') or {}
    hi = (scan or {}).get('host_info') or {}
    host_user = _names(hi.get('passwd'), 'uid')
    host_group = _names(hi.get('group'), 'gid')
    ur, gr = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
    ct_group = _names(det.get('groups'), 'gid')

    users = []
    for u in det.get('users', []):
        h_uid, h_gid = M.to_host(ur, u['uid']), M.to_host(gr, u['gid'])
        extra = sorted(g['name'] for g in det.get('groups', []) if u['name'] in g['members'] and g['gid'] != u['gid'])
        users.append({**u, 'group': ct_group.get(u['gid'], str(u['gid'])), 'groups': extra,
                      'system': (0 < u['uid'] <= SYSTEM_MAX) or u['uid'] == M.NOBODY,
                      'host_uid': h_uid, 'host_user': host_user.get(h_uid, '') if h_uid is not None else '',
                      'host_other': bool(h_uid is not None and host_user.get(h_uid) and host_user[h_uid] != u['name']),
                      'host_gid': h_gid, 'host_group': host_group.get(h_gid, '') if h_gid is not None else ''})

    def rows(rngs, names):
        if rngs is None:
            return None
        return [{**r, 'ct_end': r['ct'] + r['count'] - 1, 'host_end': r['host'] + r['count'] - 1,
                 'same': r['ct'] == r['host'],
                 'name': names.get(r['host'], '') if r['count'] == 1 else ''} for r in rngs]

    mounts = []
    for m in cfg.get('mounts', []):
        hs, cs = m.get('host_stat'), (det.get('stat') or {}).get(m['target'])
        expected = None
        if hs:  # wie der Container den Besitzer sehen müsste (auch bei gestopptem Container berechenbar)
            cu, cg = M.to_ct(ur, hs['uid']), M.to_ct(gr, hs['gid'])
            expected = {'uid': M.NOBODY if cu is None else cu, 'gid': M.NOBODY if cg is None else cg,
                        'unmapped': cu is None or cg is None}
        acl = [e for e in ((m.get('acl') or {}).get('access') or []) if e['tag'] in ('user', 'group')]
        for e in acl:
            names = host_user if e['tag'] == 'user' else host_group
            e.setdefault('name', names.get(e['id'], ''))
        mounts.append({**m, 'ct_stat': cs, 'expected': expected, 'acl_entries': acl,
                       'ct_offline': det.get('offline', []),
                       'default_acl': bool((m.get('acl') or {}).get('default'))})

    ct_user = {u['name']: u for u in det.get('users', [])}
    shares = []
    for sh in ((det.get('samba') or {}).get('shares') or []):
        if sh['name'].lower() == 'homes':
            continue
        fu, fg = sh.get('force user', ''), sh.get('force group', '')
        m = mount_for(cfg, sh.get('path', '')) if sh.get('path') else None
        u = ct_user.get(fu)
        shares.append({**sh, 'writable': sh.get('read only', 'yes').lower() in ('no', 'false', '0')
                       or sh.get('writable', sh.get('writeable', '')).lower() in ('yes', 'true', '1'),
                       'as_user': fu, 'as_uid': u['uid'] if u else None, 'as_group': fg,
                       'host_uid': M.to_host(ur, u['uid']) if u else None,
                       'mount': m, 'host_stat': (m or {}).get('host_stat')})
    # Klartext je Benutzer und Gruppe (0.5.1): wofür es ihn gibt und was er in jedem eingehängten Ordner darf
    targets = [m['target'] for m in mounts if m['target'] and (m['ct_stat'] or m['expected'])]

    def owner(m, key):
        st = m['ct_stat'] or m['expected'] or {}
        return st.get(key)
    for u in users:
        owned = [m['target'] for m in mounts if m['target'] and owner(m, 'uid') == u['uid'] and u['uid'] != 0]
        u['role'] = explain.user_role(u, cfg, shares, owned)
        u['folders'] = []
        if guest.get('status') == 'running' and not u['system']:
            for t in targets:
                a = explain.folder_access(u['name'], diagnose(guest, u['uid'], t), ct_group,
                                          bool(cfg.get('unprivileged')))
                if a:
                    u['folders'].append({'target': t, **a})
    groups = []
    for g in det.get('groups', []):
        owned = [m['target'] for m in mounts if m['target'] and owner(m, 'gid') == g['gid'] and g['gid'] != 0]
        groups.append({**g, 'role': explain.group_role(g, det.get('users', []), owned)})

    own = []
    for x in det.get('own_mounts') or []:
        o = parse_opts(x['options'])
        own.append({**x, 'kind': 'nfs' if x['fstype'].startswith('nfs') else 'smb',
                    'uid': o.get('uid'), 'gid': o.get('gid'), 'file_mode': o.get('file_mode'), 'dir_mode': o.get('dir_mode')})
    return {'guest': guest, 'cfg': cfg, 'status': status(guest), 'mapping': mapping_kind(cfg),
            'nameless': nameless(scan, guest), 'shares': shares, 'own_mounts': own,
            'exports': det.get('exports') or [],
            'running': guest.get('status') == 'running', 'errors': det.get('errors', []),
            'users': users, 'has_users': bool(det.get('users')), 'groups': groups,
            'urows': rows(ur, host_user), 'grows': rows(gr, host_group), 'mounts': mounts}


def storage(scan):
    """Alle Host-Ordner und Freigaben, die in Container eingehängt sind, mit der Sicht jedes Containers.

    Dazu NFS/SMB-Freigaben des Hosts, die in keinem Container stecken."""
    hi = (scan or {}).get('host_info') or {}
    host_user, host_group = _names(hi.get('passwd'), 'uid'), _names(hi.get('group'), 'gid')
    by_source = {}
    for g in (scan or {}).get('guests', []):
        cfg = g.get('config') or {}
        if g['type'] != 'lxc' or not cfg:
            continue
        ur, gr = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
        for m in cfg.get('mounts', []):
            if m['kind'] != 'bind':
                continue
            s = by_source.setdefault(m['source'], {
                'source': m['source'], 'host_stat': m.get('host_stat'), 'fs': m.get('fs'),
                'fs_kind': m.get('fs_kind', 'lokal'), 'acl': m.get('acl'), 'users': []})
            hs = m.get('host_stat')
            cs = ((g.get('details') or {}).get('stat') or {}).get(m['target'])
            if cs:
                seen = {'uid': cs['uid'], 'gid': cs['gid'], 'user': cs['user'], 'group': cs['group'], 'live': True}
            elif hs:
                cu, cg = M.to_ct(ur, hs['uid']), M.to_ct(gr, hs['gid'])
                seen = {'uid': M.NOBODY if cu is None else cu, 'gid': M.NOBODY if cg is None else cg,
                        'user': '', 'group': '', 'live': False}
            else:
                seen = None
            s['users'].append({'vmid': g['vmid'], 'name': g['name'], 'status': status(g),
                               'mapping': mapping_kind(cfg), 'target': m['target'], 'readonly': m.get('readonly'),
                               'seen': seen,
                               'nobody': bool(seen) and (seen['uid'] == M.NOBODY or seen['gid'] == M.NOBODY)})
    items = []
    for s in by_source.values():
        hs = s['host_stat'] or {}
        s['host_user'] = host_user.get(hs.get('uid'), '')
        s['host_group'] = host_group.get(hs.get('gid'), '')
        s['users'].sort(key=lambda u: u['vmid'])
        s['privileged'] = sum(1 for u in s['users'] if u['mapping'] == 'privilegiert')
        s['problems'] = sum(1 for u in s['users'] if u['nobody'])
        items.append(s)
    items.sort(key=lambda s: (-len(s['users']), s['source']))
    used = {s['source'] for s in items}
    unused = [m for m in hi.get('mounts', []) if m['fstype'].startswith('nfs') or m['fstype'] in ('cifs', 'smb3')]
    unused = [m for m in unused if not any(u == m['target'] or u.startswith(m['target'].rstrip('/') + '/') for u in used)]
    calculated = any(u['seen'] and not u['seen']['live'] for s in items for u in s['users'])
    return {'sources': items, 'unused': unused, 'calculated': calculated}


def mount_for(cfg, path):
    """Mount, in dem ein Pfad liegt (längstes passendes Ziel), oder None (dann Dateisystem des Containers)."""
    best = None
    for m in cfg.get('mounts', []):
        t = m['target'].rstrip('/')
        if t and (path == t or path.startswith(t + '/')) and (best is None or len(t) > len(best['target'])):
            best = m
    return best


def diagnose(guest, uid, path, live=None, acl_live=None, user=None, readonly=False):
    """Rechte-Rechner für einen Benutzer (Nummer im Container) und einen Pfad im Container.
    live: frisch abgefragte stat-Werte (für Pfade, die der Scan nicht kennt).
    acl_live: ACL-Einträge des Ziels, im Container gelesen (getfacl); ersetzen dann die ACL vom Host.
    user: {name, uid, gid, gids} statt eines Benutzers aus dem Container (z. B. eine Docker-App, AP 6.2).
    readonly: zusätzlich schreibgeschützt (Docker-Mount mit :ro).
    None, wenn Benutzer unbekannt ist (z. B. Container gestoppt)."""
    cfg, det = guest.get('config') or {}, guest.get('details') or {}
    user = user or next((u for u in det.get('users', []) if u['uid'] == uid), None)
    if not user:
        return None
    m = mount_for(cfg, path)
    if m and (m['target'] in det.get('offline', []) or m.get('fs_kind') == 'offline'):
        return {'enter': False, 'read': False, 'write': False, 'cause': 'offline', 'steps': [],
                'hints': [('Der Ordner antwortet nicht. Ist das NAS ausgeschaltet?',)]}
    gids = user['gids'] if 'gids' in user else [g['gid'] for g in det.get('groups', []) if user['name'] in g['members']]
    ur, gr = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
    acl = None
    if m and path == m['target'] and m.get('acl'):  # ACL kommt vom Host: Nummern in die Sicht des Containers
        entries = []
        for e in m['acl'].get('access') or []:
            if e.get('id') is not None:
                ct_id = M.to_ct(ur if e['tag'] == 'user' else gr, e['id'])
                if ct_id is None:
                    continue  # im Container nicht sichtbar, kann niemanden dort betreffen
                e = {**e, 'id': ct_id}
            entries.append(e)
        acl = {'access': entries}
    if acl_live is not None:
        acl = {'access': acl_live}
    stats = {**(det.get('stat') or {}), **(live or {})}
    # Eine Docker-App bekommt den Ordner direkt eingehängt: die Ordner davor im LXC sieht sie nicht
    chain = [] if user.get('app') else [{'path': q, 'stat': stats.get(q)} for q in parents(path)]
    chain.append({'path': path, 'stat': stats.get(path), 'acl': acl})
    fs_opts = (((m or {}).get('fs') or {}).get('options') or '').split(',')
    res = access.check({'uid': user['uid'], 'gid': user['gid'], 'gids': gids}, chain,
                       readonly=readonly or bool(m and m.get('readonly')) or (bool(m) and 'ro' in fs_opts),
                       unprivileged=bool(cfg.get('unprivileged')), fs_kind=(m or {}).get('fs_kind', ''))
    if m and path != m['target'] and (m.get('acl') or {}).get('access'):
        res['hints'].append(('ACLs unterhalb von § wurden nicht geprüft.', m['target']))
    return res


def app_user(guest, app):
    """Eine Docker-App als „Benutzer“ für den Rechte-Rechner: {name, uid, gid, gids, app, writer} oder None."""
    w = docker.writer(app)
    if w['uid'] is None or w['gid'] is None:
        return None
    return {'name': app['name'], 'uid': w['uid'], 'gid': w['gid'], 'gids': [], 'app': app['name'], 'writer': w}


def short_path(path):
    """Lange Kennungen (anonyme Docker-Volumes: 64 Hex-Zeichen) für die Anzeige kürzen: b5db0401…e55b."""
    return re.sub(r'([0-9a-f]{8})[0-9a-f]{40,}([0-9a-f]{4})', r'\1…\2', path or '')


def docker_apps(scan, guest):
    """Docker-Abschnitt der Container-Seite: je App, als wer sie schreibt (im LXC und auf dem Host) und
    was sie in jedem eingehängten Ordner darf."""
    cfg, det = guest.get('config') or {}, guest.get('details') or {}
    dk = det.get('docker')
    if dk is None:
        return None
    hi = (scan or {}).get('host_info') or {}
    host_user = _names(hi.get('passwd'), 'uid')
    ur, gr = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
    ct_user, ct_group = _names(det.get('users'), 'uid'), _names(det.get('groups'), 'gid')
    stats = det.get('stat') or {}
    apps = []
    for app in dk.get('apps') or []:
        w = docker.writer(app)
        u = app_user(guest, app)
        h_uid = M.to_host(ur, w['uid']) if w['uid'] is not None else None
        h_gid = M.to_host(gr, w['gid']) if w['gid'] is not None else None
        folders = []
        for mnt in docker.binds(app):
            st = stats.get(mnt['source'])
            res = diagnose(guest, None, mnt['source'], user=u, readonly=not mnt.get('rw', True)) if u and st else None
            lxc_mount = mount_for(cfg, mnt['source'])
            folders.append({**mnt, 'stat': st, 'res': res, 'volume': mnt.get('type') == 'volume',
                            'short': short_path(mnt['source']),
                            'owner_name': ct_user.get((st or {}).get('uid'), '') if st else '',
                            'group_name': ct_group.get((st or {}).get('gid'), '') if st else '',
                            'lxc_mount': lxc_mount,
                            'host_owner': M.to_host(ur, st['uid']) if st else None})
        apps.append({**app, 'writer': w, 'ct_name': ct_user.get(w['uid'], '') if w['uid'] is not None else '',
                     'ct_group': ct_group.get(w['gid'], '') if w['gid'] is not None else '',
                     'host_uid': h_uid, 'host_gid': h_gid,
                     'host_name': host_user.get(h_uid, '') if h_uid is not None else '',
                     'folders': folders, 'can_check': bool(u)})
    return {'apps': apps, 'error': dk.get('error', ''), 'more': dk.get('more', 0),
            'running': guest.get('status') == 'running'}


def diagnose_form(guest):
    """Auswahl für die Diagnose-Seite: Benutzer (normale zuerst, dann System) und Ordner."""
    det, cfg = guest.get('details') or {}, guest.get('config') or {}
    users = sorted(det.get('users', []), key=lambda u: u['uid'])
    normal = [u for u in users if u['uid'] == 0 or SYSTEM_MAX < u['uid'] != M.NOBODY]
    system = [u for u in users if u not in normal]
    paths = [m['target'] for m in cfg.get('mounts', []) if m['target']]
    apps = [a for a in docker.apps_of(guest) if app_user(guest, a)]
    return {'users': normal, 'system': system, 'paths': paths, 'apps': apps}


STORAGE_TYPES = {'dir': 'Ordner', 'lvmthin': 'LVM-Thin', 'lvm': 'LVM', 'zfspool': 'ZFS', 'nfs': 'NFS', 'cifs': 'SMB',
                 'pbs': 'Proxmox Backup Server', 'cephfs': 'CephFS', 'rbd': 'Ceph RBD', 'btrfs': 'Btrfs'}
CONTENT = {'images': 'VM-Platten', 'rootdir': 'Container-Platten', 'backup': 'Backups', 'iso': 'ISO-Abbilder',
           'vztmpl': 'Container-Vorlagen', 'snippets': 'Snippets', 'import': 'Import'}


def _under(path, base):
    base = base.rstrip('/') or '/'
    return path == base or path.startswith(base + '/')


def host(scan):
    """Seite „Host“: Speicher aus storage.cfg, Netzfreigaben, Host-Ordner der Container, Benutzer, subuid/subgid.
    Nur lesen und zusammenfassen."""
    hi = (scan or {}).get('host_info') or {}
    mounts = hi.get('mounts') or []
    lxcs = [g for g in (scan or {}).get('guests', []) if g['type'] == 'lxc' and g.get('config')]

    storages = []
    for st in hi.get('storage') or []:
        p, sid, kind = st['props'], st['id'], st['type']
        path = p.get('path') or (f'/mnt/pve/{sid}' if kind in ('nfs', 'cifs', 'cephfs') else '')
        where = {'nfs': f"{p.get('server', '?')}:{p.get('export', '?')}",
                 'cifs': f"//{p.get('server', '?')}/{p.get('share', '?')}",
                 'lvmthin': f"{p.get('vgname', '?')}/{p.get('thinpool', '?')}", 'lvm': p.get('vgname', ''),
                 'zfspool': p.get('pool', ''), 'pbs': f"{p.get('server', '?')} · {p.get('datastore', '?')}"}.get(kind, path)
        mounted = None
        if kind in ('nfs', 'cifs', 'cephfs'):
            mounted = any(m['target'] == path for m in mounts)
        used, offline = [], False
        for g in lxcs:
            cfg = g['config']
            vols = [cfg.get('raw', {}).get('rootfs', '')] + [m['source'] for m in cfg.get('mounts', []) if m['kind'] == 'volume']
            hit = [m for m in cfg.get('mounts', []) if m['kind'] == 'bind' and path and _under(m['source'], path)]
            if any(v.startswith(sid + ':') for v in vols) or hit:
                used.append({'vmid': g['vmid'], 'name': g['name'], 'bind': bool(hit)})
            offline = offline or any(m.get('fs_kind') == 'offline' for m in hit)
        content = [c for c in (p.get('content') or '').split(',') if c]
        storages.append({'id': sid, 'type': kind, 'type_label': STORAGE_TYPES.get(kind, kind), 'where': where,
                         'path': path, 'content': content, 'mounted': mounted, 'disabled': p.get('disable') == '1',
                         'shared': p.get('shared') == '1', 'used': used, 'offline': offline,
                         'backup_only': not used and bool(content) and set(content) <= {'backup', 'iso', 'vztmpl', 'snippets', 'import'}})

    known = {s['path'] for s in storages if s['path']}
    manual = [m for m in mounts if (m['fstype'].startswith('nfs') or m['fstype'] in ('cifs', 'smb3')) and m['target'] not in known]

    folders = {}
    for g in lxcs:
        for m in g['config'].get('mounts', []):
            if m['kind'] == 'bind' and not any(s['path'] and _under(m['source'], s['path']) for s in storages):
                f = folders.setdefault(m['source'], {'source': m['source'], 'host_stat': m.get('host_stat'),
                                                     'fs_kind': m.get('fs_kind', ''), 'users': []})
                f['users'].append({'vmid': g['vmid'], 'name': g['name']})

    # subuid/subgid: wofür wird welcher Eintrag gebraucht?
    def subids(key, kind):
        rows = []
        for e in hi.get(key) or []:
            users = []
            if e['user'] == 'root':
                for g in lxcs:
                    rng = M.ranges(g['config'], kind)
                    if rng and any(e['start'] <= r['host'] < e['start'] + e['count'] for r in rng):
                        users.append(g['vmid'])
            rows.append({**e, 'end': e['start'] + e['count'] - 1, 'containers': sorted(set(users))})
        return rows

    return {'storages': storages, 'manual': manual, 'folders': sorted(folders.values(), key=lambda f: f['source']),
            'users': sorted((u for u in hi.get('passwd') or [] if is_person(u['uid'])), key=lambda u: u['uid']),
            'groups': sorted((g for g in hi.get('group') or [] if is_person(g['gid'])), key=lambda g: g['gid']),
            'subuid': subids('subuid', 'u'), 'subgid': subids('subgid', 'g'),
            'has_storage': 'storage' in hi}
