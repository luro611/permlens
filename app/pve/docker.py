"""Docker-Einblick (AP 6.2, Wächter 8): welche Apps in einem LXC laufen, als wer sie schreiben und in welche Ordner.

Docker ist beim Mapping die dritte Ebene: Host → LXC → App. Ohne eigenen User-Namespace (der Normalfall) hat eine
App im LXC dieselben Nummern wie der LXC selbst. Schreibt sie als 1000 in einen eingehängten Ordner, gehört die
Datei im LXC der 1000 und auf dem Host der Nummer, auf die der LXC die 1000 abbildet.

Der Wächter gibt aus `docker inspect` nur ausgewählte Felder heraus (nie Passwörter aus den Umgebungsvariablen)."""
import json
from collections import Counter

from . import parse, ssh

MAX_APPS = 30          # mehr Apps je LXC liest der Scan nicht einzeln ein
# Variablen, mit denen gängige Images die Nummer festlegen (linuxserver.io, paperless-ngx, …), in dieser Reihenfolge
UID_VARS = ('PUID', 'USERMAP_UID', 'USER_ID', 'APP_UID', 'UID')
GID_VARS = ('PGID', 'USERMAP_GID', 'GROUP_ID', 'APP_GID', 'GID')


def _json(r):
    try:
        return json.loads(r.out)
    except ValueError:
        return None


def collect(host, port, vmid, stat_cmd, timeout):
    """Docker-Apps eines laufenden LXC einlesen. None, wenn es dort kein Docker gibt.
    Ergebnis: {apps: [...], error: ''}; je App die gefilterten Felder aus docker-inspect und die Prozesse."""
    r = ssh.run(host, ['docker-ps', str(vmid)], port, timeout=30)
    data = _json(r) or {}
    if not data.get('docker'):
        return None
    out = {'apps': [], 'error': '' if r.ok else (data.get('error') or ssh.explain(r)), 'more': 0}
    apps = data.get('apps') or []
    out['more'] = max(0, len(apps) - MAX_APPS)
    for a in apps[:MAX_APPS]:
        app = dict(a)
        ri = ssh.run(host, ['docker-inspect', str(vmid), a['name']], port, timeout=30)
        info = _json(ri) if ri.ok else None
        if info:
            app.update(info)
        else:
            app['error'] = ((_json(ri) or {}).get('error') or ssh.explain(ri))
        if app.get('state') == 'running':
            rt = ssh.run(host, ['docker-top', str(vmid), a['name']], port, timeout=30)
            app['processes'] = (_json(rt) or {}).get('processes') if rt.ok else None
        out['apps'].append(app)
    # Rechte der eingehängten Ordner im LXC (Quellen der App-Mounts und die Ordner davor)
    from .scan import parents
    paths = sorted({m['source'] for app in out['apps'] for m in app.get('mounts') or []
                    if m.get('source', '').startswith('/')})
    every = sorted({q for p in paths for q in parents(p)} | set(paths))
    if every:
        rs = ssh.run(host, ['pct', 'exec', str(vmid), '--'] + stat_cmd + every, port, timeout=timeout)
        out['stat'] = parse.stat(rs.out)
    return out


def _first(env, names):
    for n in names:
        if str((env or {}).get(n, '')).isdigit():
            return int(env[n]), n
    return None, ''


def _user_field(user):
    """'1000:1000' → (1000, 1000); 'node' → (None, None); '' → (0, 0) (Standard: root)."""
    if not user:
        return 0, 0
    u, _, g = user.partition(':')
    return (int(u) if u.isdigit() else None), (int(g) if g.isdigit() else (None if g else (0 if u == '0' else None)))


def writer(app):
    """Als welche Nummern schreibt die App? {uid, gid, origin, origin_var, puid, top_differs}.
    origin: 'prozesse' (gemessen mit docker top), 'variable' (PUID o. ä.), 'user' (USER im Image/Container),
    'standard' (nichts festgelegt: root). uid/gid None = unbekannt (z. B. Benutzername statt Nummer)."""
    env = app.get('env') or {}
    puid, puid_var = _first(env, UID_VARS)
    pgid, _ = _first(env, GID_VARS)
    cu, cg = _user_field(app.get('user', ''))
    procs = app.get('processes') or []
    res = {'puid': puid, 'pgid': pgid, 'origin_var': puid_var, 'top_differs': False}
    if procs:
        # Viele Images starten als root und wechseln dann zu PUID: zählt, als wer die eigentlichen Programme laufen
        others = [(p['uid'], p['gid']) for p in procs if p['uid'] != 0]
        uid, gid = Counter(others).most_common(1)[0][0] if others else (0, 0)
        res.update(uid=uid, gid=gid, origin='prozesse')
        res['top_differs'] = puid is not None and puid != uid
        return res
    if puid is not None:
        return {**res, 'uid': puid, 'gid': pgid if pgid is not None else puid, 'origin': 'variable'}
    if app.get('user'):
        return {**res, 'uid': cu, 'gid': cg, 'origin': 'user'}
    return {**res, 'uid': 0, 'gid': 0, 'origin': 'standard'}


def apps_of(guest):
    det = (guest or {}).get('details') or {}
    return ((det.get('docker') or {}).get('apps')) or []


def find_app(guest, name):
    return next((a for a in apps_of(guest) if a.get('name') == name), None)


def binds(app):
    """Ordner des LXC, die die App einhängt (Bind-Mounts und Volumes mit Pfad)."""
    return [m for m in app.get('mounts') or [] if (m.get('source') or '').startswith('/')]
