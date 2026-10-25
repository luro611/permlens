"""Änderungen am Host (Phase 6, AP 6.5, ab Wächter 9): Mount-Punkte und Mapping eines bestehenden Containers.

Wie bei den Änderungen im Container (change.py): erst die Vorschau, ausgeführt wird derselbe Plan noch einmal frisch
berechnet. Alles nur für gestoppte Container aus /etc/permlens/host-aendern-erlaubt. Vor der Änderung sichert der
Wächter /etc/pve/lxc/<Nr>.conf selbst auf dem Host; Rückgängig spielt diese Sicherung zurück, aber nur, wenn die
Datei seitdem unverändert ist. PermLens kann keinen eigenen Text in die Datei schreiben, nur die festen Befehlsformen
des Wächters nutzen. Dateien im Container nachziehen macht PermLens nicht selbst: Braucht ein neues Mapping das, zeigt die Vorschau den
Befehl zum Kopieren, und Ausführen geht erst nach einem Häkchen (Entscheidung Lutz, 2026-10-25). Neue Container legt LXC Forge an, nicht PermLens.

Texte für die Oberfläche stehen als Tupel (deutscher Text mit §, Werte …) und werden in der Vorlage übersetzt."""
import json
import re
import shlex
from contextlib import closing

from .. import db
from . import bauplan, change, mapping as M, parse, ssh

ACTIONS = ('mp-hinzu', 'mp-weg', 'mapping', 'conf-zurueck')
FIELDS = ('key', 'src', 'dst', 'ro', 'u', 'g', 'backup')
GUARD_MIN = 9
MP_KEY = re.compile(r'^mp([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])$')
MP_PATH = re.compile(r'^/[A-Za-z0-9._@+~/-]*$')  # wie im Wächter: ohne Komma, =, : und Leerzeichen
TIMEOUT = 90


def guard_ok(version):
    return str(version or '').isdigit() and int(version) >= GUARD_MIN


def path_ok(p):
    return bool(MP_PATH.match(p or '')) and '/../' not in p + '/' and '/./' not in p + '/' and p != '/'


def under(path, folders):
    return any(path == f or path.startswith(f.rstrip('/') + '/') for f in folders or [])


def live(host, port, vmid):
    """Frischer Stand vom Host: Freigaben des Wächters, Status, Einstellungen, /etc/subuid und /etc/subgid."""
    info, r = ssh.guard_info(host, port)
    st = ssh.run(host, ['pct', 'status', str(vmid)], port, timeout=30)
    cf = ssh.run(host, ['pct', 'config', str(vmid)], port, timeout=30)
    su = ssh.run(host, ['cat', '/etc/subuid'], port, timeout=20)
    sg = ssh.run(host, ['cat', '/etc/subgid'], port, timeout=20)
    bad = next((x for x in (r, cf) if not x.ok), None)
    return {'guard': str(info.get('guard') or ''), 'host_ids': str(info.get('host_ids') or ''),
            'host_paths': [p for p in info.get('host_paths') or [] if isinstance(p, str)],
            'status': st.out.strip().removeprefix('status: ') if st.ok else '',
            'config': parse.pct_config(cf.out) if cf.ok else None, 'conf_text': cf.out if cf.ok else '',
            'subuid': parse.subid(su.out) if su.ok else [], 'subgid': parse.subid(sg.out) if sg.ok else [],
            'error': (ssh.explain(bad),) if bad else None}


def _guest(last, vmid):
    return next((g for g in (last or {}).get('guests', []) if g['vmid'] == vmid and g['type'] == 'lxc'), None)


def _with_live(last, guest, cfg, lv):
    """Scan mit den frisch gelesenen Einstellungen dieses Containers (Besitzer der Ordner aus dem Scan)."""
    stats = {m['source']: m.get('host_stat') for m in ((guest or {}).get('config') or {}).get('mounts', [])}
    cfg = {**cfg, 'mounts': [{**m, 'host_stat': stats.get(m['source'])} for m in cfg.get('mounts', [])]}
    g2 = {**(guest or {}), 'config': cfg}
    hi = {**((last or {}).get('host_info') or {}), 'subuid': lv['subuid'], 'subgid': lv['subgid']}
    return {**(last or {}), 'host_info': hi,
            'guests': [g2 if g['vmid'] == g2.get('vmid') else g for g in (last or {}).get('guests', [])]}, g2


def _ids(text):
    out = set()
    for x in re.split(r'[,\s]+', str(text or '').strip()):
        if x:
            if not x.isdigit() or not M.PASS_MIN <= int(x) <= M.PASS_MAX:
                return None
            out.add(int(x))
    return out


def _owner_text(st, cfg):
    """'1000:1000' bzw. mit nobody, wie der Container den Ordner sieht."""
    ru, rg = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
    u, g = M.to_ct(ru, st['uid']), M.to_ct(rg, st['gid'])
    return f"{'nobody' if u is None else u}:{'nogroup' if g is None else g}", u is None or g is None


# ---------------------------------------------------------------- die einzelnen Aktionen
def _mp_hinzu(p, last, guest, cfg, params, lv):
    src = str(params.get('src', '')).strip().rstrip('/')
    dst = str(params.get('dst', '')).strip().rstrip('/') or src
    ro = bool(params.get('ro'))
    used = {k for k, _ in cfg.get('lines', [])} | set(cfg.get('raw', {}))
    key = str(params.get('key', '')).strip() or next((f'mp{i}' for i in range(256) if f'mp{i}' not in used), '')
    p['params'] = {'key': key, 'src': src, 'dst': dst, **({'ro': '1'} if ro else {})}
    p['title'] = ('Mount-Punkt hinzufügen',)
    if not path_ok(src) or not path_ok(dst):
        return ('Ordner § bzw. Ziel § ist ungültig: absoluter Pfad ohne Leerzeichen, Komma, Doppelpunkt und „..“.', src, dst)
    if not MP_KEY.match(key) or key in used:
        return ('Es gibt keinen freien Mount-Punkt (mp0 bis mp255).',) if not key else ('§ ist schon belegt.', key)
    if any((m.get('target') or '').rstrip('/') == dst for m in cfg.get('mounts', [])):
        return ('Im Container ist § schon ein Einhängepunkt.', dst)
    known = {f['path']: f for f in bauplan.known_folders(last)}
    if src not in known and not under(src, lv['host_paths']):
        return ('Einhängen darf PermLens nur Ordner, die schon in einem Container eingehängt sind oder unter einem '
                'freigegebenen Ordner liegen (Zeilen mit / in /etc/permlens/host-aendern-erlaubt).',)
    line = f"{src},mp={dst}" + (',ro=1' if ro else '')
    p['cmd'] = [['pct', 'set', str(p['vmid']), f'--{key}', line]]
    p['reason'] = ('Der Container bekommt Zugriff auf einen Ordner des Hosts. Was er dort darf, bestimmen Besitzer, '
                   'Rechte und das Mapping. Der Container muss dafür gestoppt sein.',)
    p['before'] = [('Container § hat § eingehängte Ordner.', p['vmid'], len(cfg.get('mounts', [])))]
    p['after'] = [('Zusätzlich § → § im Container.', src, dst)] + ([('Nur lesen.',)] if ro else [])
    p['conf_after'] = [f'{key}: {line}']
    st = (known.get(src) or {}).get('stat')
    if st:
        owner, nobody = _owner_text(st, cfg)
        p['after'].append(('Der Ordner gehört auf dem Host §:§, im Container §.', st['uid'], st['gid'], owner))
        if nobody:
            p['info'].append(('Der Container sieht den Ordner als nobody. Damit er dort schreiben kann, danach im '
                              'Mapping-Assistenten (Bestehender Container) die Nummern durchreichen.',))
    else:
        p['info'].append(('Besitzer und Rechte des Ordners kennt PermLens noch nicht. Nach dem Einhängen „Neu einlesen“ und mit der Diagnose prüfen.',))
    return None


def _mp_weg(p, last, guest, cfg, params, lv):
    key = str(params.get('key', '')).strip()
    p['params'] = {'key': key}
    p['title'] = ('Mount-Punkt entfernen',)
    m = next((x for x in cfg.get('mounts', []) if x.get('key') == key and not x.get('entry')), None)
    if not MP_KEY.match(key) or not m:
        return ('Den Mount-Punkt § gibt es in diesem Container nicht.', key)
    if m.get('kind') != 'bind':
        return ('§ ist ein Speicher-Volume, kein Ordner des Hosts. Das entfernt PermLens nicht (dafür die Oberfläche von Proxmox).', key)
    p['cmd'] = [['pct', 'set', str(p['vmid']), '--delete', key]]
    p['reason'] = ('Der Container verliert den Zugriff auf diesen Ordner. Die Dateien im Ordner auf dem Host bleiben, wie sie sind.',)
    p['before'] = [('§ → § im Container.', m['source'], m['target'])]
    p['after'] = [('§ ist nicht mehr eingehängt.', m['source'])]
    p['conf_before'] = [f"{key}: {dict(cfg.get('lines', [])).get(key, '')}"]
    apps = [a['name'] for a in ((guest or {}).get('docker') or {}).get('apps', [])
            if any(str(x.get('source', '')).startswith(m['target'].rstrip('/') + '/') or x.get('source') == m['target']
                   for x in a.get('mounts', []))]
    if apps:
        p['info'].append(('Diese Docker-Apps nutzen den Ordner: §. Sie finden ihn danach nicht mehr.', ', '.join(apps)))
    return None


def _mapping(p, last, guest, cfg, params, lv):
    sel_u, sel_g = _ids(params.get('u')), _ids(params.get('g'))
    p['params'] = {'u': str(params.get('u', '')).strip(), 'g': str(params.get('g', '')).strip()}
    p['title'] = ('Mapping ändern',)
    if sel_u is None or sel_g is None:
        return ('Nummern von 1 bis 65533 angeben, mit Komma getrennt.',)
    if not cfg.get('unprivileged'):
        return ('Container § ist privilegiert. Er sieht die Nummern des Hosts ohnehin 1:1.', p['vmid'])
    scan2, _ = _with_live(last, guest, cfg, lv)
    ep = bauplan.existing_plan(scan2, p['vmid'], {'chosen': '1', 'u': sorted(sel_u), 'g': sorted(sel_g)})
    if ep['errors']:
        return ep['errors'][0]
    if ep.get('nothing'):
        return ('Mit dieser Auswahl ändert sich nichts: Alle gewählten Nummern werden schon durchgereicht.',)
    if ep['moved']:  # Nachziehen bleibt von Hand (Entscheidung Lutz, 2026-10-25): Ausführen erst nach Häkchen
        p['need_ack'] = True
        p['fix'] = ep['cmds']['fix']
        p['moved'] = [('Benutzer § (§): heute § auf dem Host', n, name or '–', old) if kind == 'u'
                      else ('Gruppe § (§): heute § auf dem Host', n, name or '–', old) for kind, n, old, name in ep['moved']]
    nu, ng = M.plan_ranges(ep['new_u']), M.plan_ranges(ep['new_g'])
    subs = [('subuid', x) for x in M.subid_missing(nu, lv['subuid'])] + [('subgid', x) for x in M.subid_missing(ng, lv['subgid'])]
    if any(not re.match(r'^root:[0-9]+:1$', x) for _, x in subs):
        return ('In /etc/subuid oder /etc/subgid fehlt der Standardbereich root:100000:65536. Den trägt PermLens nicht selbst ein.',)
    p['cmd'] = [['host-subid', name, x.split(':')[1]] for name, x in subs]
    p['cmd'].append(['host-idmap', str(p['vmid'])] + [f"u:{r['ct']}:{r['host']}:{r['count']}" for r in nu]
                    + [f"g:{r['ct']}:{r['host']}:{r['count']}" for r in ng])
    p['reason'] = ('Danach sieht der Container diese Nummern des Hosts als dieselben Benutzer bzw. Gruppen. Der Container muss dafür gestoppt sein.',)
    p['before'] = [('Durchgereicht: Benutzer §, Gruppen §.', ', '.join(map(str, ep['now_u'])) or '–', ', '.join(map(str, ep['now_g'])) or '–')]
    p['after'] = [('Durchgereicht: Benutzer §, Gruppen §.', ', '.join(map(str, ep['new_u'])) or '–', ', '.join(map(str, ep['new_g'])) or '–')]
    for m in ep['mounts']:
        if m.get('ct_after'):
            p['after'].append(('§ gehört im Container dann §.', m['dst'], ':'.join('nobody' if n == M.NOBODY else str(n) for n in m['ct_after'])))
    p['conf_before'] = [f"lxc.idmap: {r['kind']} {r['ct']} {r['host']} {r['count']}" for r in cfg.get('idmap', [])]
    p['conf_after'] = ep['idmap']
    p['subs'] = [f'/etc/{name}: {x}' for name, x in subs]
    for s in {(s['vmid'], s['name'], s['id']): s for s in ep['shared']}:  # Benutzer und Gruppe nur einmal
        p['info'].append(('Container § (§) sieht Nummer § ebenfalls als dieselbe.', *s))
    if not ep['standard']:
        p['info'].append(('Das bisherige Mapping verschiebt nicht nach dem Proxmox-Standard (100000). Es wird durch den Standard plus die gewählten Nummern ersetzt.',))
    if subs:
        p['info'].append(('Die Zeilen in /etc/subuid und /etc/subgid bleiben beim Rückgängigmachen stehen. Sie erlauben root nur diese Nummern und schaden nicht.',))
    return None


def _conf_zurueck(p, last, guest, cfg, params, lv):
    name = str(params.get('backup', '')).strip()
    nr = str(params.get('nr', '')).strip()
    p['params'] = {'backup': name, 'nr': nr}
    p['title'] = ('Einstellungen zurückspielen',)
    e = change.entry(int(nr)) if nr.isdigit() else None
    if not e or e['vmid'] != p['vmid'] or not re.match(rf"^{p['vmid']}-[0-9]{{8}}-[0-9]{{6}}-[0-9a-f]{{6}}$", name):
        return ('Diese Sicherung kennt PermLens nicht.',)
    p['cmd'] = [['host-restore', str(p['vmid']), name]]
    p['reason'] = ('Spielt die Einstellungen des Containers so zurück, wie sie vor Änderung Nr. § waren. Das geht nur, solange sie seitdem niemand geändert hat.', nr)
    old = parse.pct_config(e.get('backup') or '')
    p['before'] = [('Heute: § eingehängte Ordner, § lxc.idmap-Zeilen.', len(cfg.get('mounts', [])), len(cfg.get('idmap', [])))]
    p['after'] = [('Danach: § eingehängte Ordner, § lxc.idmap-Zeilen.', len(old.get('mounts', [])), len(old.get('idmap', [])))]
    now, before = [f'{k}: {v}' for k, v in cfg.get('lines', [])], [f'{k}: {v}' for k, v in old.get('lines', [])]
    p['conf_before'] = [x for x in now if x not in before]
    p['conf_after'] = [x for x in before if x not in now]
    p['undo'] = None
    return None


HANDLERS = {'mp-hinzu': _mp_hinzu, 'mp-weg': _mp_weg, 'mapping': _mapping, 'conf-zurueck': _conf_zurueck}


def plan(action, last, vmid, params, lv):
    """Vorschau einer Host-Änderung. lv: frischer Stand vom Host (live). 'error' ist leer oder ein Tupel."""
    guest = _guest(last, vmid)
    cfg = (lv or {}).get('config')
    p = {'host': True, 'action': action, 'vmid': vmid, 'ct_name': (guest or {}).get('name') or (cfg or {}).get('hostname', ''),
         'params': {}, 'title': ('Änderung am Host',), 'cmd': [], 'shell': '', 'rating': 'risiko', 'reason': None,
         'before': [], 'after': [], 'info': [], 'undo': {'action': 'conf-zurueck', 'params': {}}, 'undo_shell': '',
         'error': None, 'effects': [], 'path': '', 'conf_before': [], 'conf_after': [], 'subs': [], 'allowed': False,
         'status': (lv or {}).get('status', ''), 'need_ack': False, 'fix': '', 'moved': []}
    if action not in HANDLERS:
        p['error'] = ('Diese Änderung kennt PermLens nicht.',)
        return p
    if lv.get('error'):
        p['error'] = lv['error']
        return p
    if not guard_ok(lv['guard']):
        p['error'] = ('Für Änderungen am Host braucht es das Wächter-Script Version §. Auf diesem Proxmox läuft Version §: Einstellungen → „Neu einrichten“.', GUARD_MIN, lv['guard'] or '?')
        return p
    if not cfg:
        p['error'] = ('Diesen Container gibt es nicht.',)
        return p
    p['error'] = HANDLERS[action](p, last, guest, cfg, params or {}, lv)
    if not p['error'] and lv['status'] != 'stopped':
        p['error'] = ('Container § läuft. Änderungen am Host gehen nur bei gestopptem Container: erst herunterfahren (in Proxmox oder mit pct shutdown §), dann diese Seite neu laden.', vmid, vmid)
    if not p['error'] and 'lock' in cfg.get('raw', {}):
        p['error'] = ('Der Container ist gesperrt (lock: §). Erst wenn Proxmox fertig ist, geht es weiter.', cfg['raw']['lock'])
    if p['cmd']:
        p['shell'] = '\n'.join(shlex.join(c) for c in p['cmd'])
        if p['undo']:
            p['undo_shell'] = shlex.join(['host-restore', str(vmid), '<Sicherung>'])
    p['allowed'] = change.write_allowed(lv['host_ids'], vmid)
    if p['error'] and not p['cmd']:
        p['shell'] = ''
    return p


# ---------------------------------------------------------------- Ausführen und Protokoll
def _verify(p, host, port):
    """Nach dem Ausführen nachlesen: Stehen die Einstellungen so da, wie die Vorschau gesagt hat?"""
    r = ssh.run(host, ['pct', 'config', str(p['vmid'])], port, timeout=30)
    if not r.ok:
        return False
    cfg, q = parse.pct_config(r.out), p['params']
    lines = dict(cfg.get('lines', []))
    if p['action'] == 'mp-hinzu':
        m = next((x for x in cfg['mounts'] if x.get('key') == q['key']), None)
        return bool(m) and m['source'] == q['src'] and m['target'] == q['dst'] and m['readonly'] == bool(q.get('ro'))
    if p['action'] == 'mp-weg':
        return q['key'] not in lines
    if p['action'] == 'mapping':
        return [f"lxc.idmap: {r['kind']} {r['ct']} {r['host']} {r['count']}" for r in cfg['idmap']] == p['conf_after']
    old = parse.pct_config(change.entry(int(q['nr']))['backup'] or '')
    return cfg.get('lines') == old.get('lines')


def execute(p, host, port, client='', undo_of=None, before_text=''):
    """Plan ausführen (Befehl für Befehl, Abbruch beim ersten Fehler), nachprüfen und protokollieren.
    before_text: Einstellungen vor der Änderung (pct config), zum Anzeigen beim Rückgängigmachen."""
    backup, detail, ok = None, '', True
    for args in p['cmd']:
        r = ssh.run(host, [str(a) for a in args], port, timeout=TIMEOUT)
        try:
            data = json.loads(r.out) if r.out.strip().startswith('{') else {}
        except ValueError:
            data = {}
        backup = data.get('backup') or backup
        if not r.ok or not data.get('ok'):
            ok = False
            detail = (r.err.replace('permlens-guard: ', 'Wächter: ').strip() if r.rc == ssh.DENIED
                      else data.get('error') or ssh.explain(r))
            break
    if ok:
        verified = _verify(p, host, port)
        result = 'ok' if verified else 'abweichung'
        detail = '' if verified else 'Die Befehle liefen durch, aber beim Nachlesen sehen die Einstellungen anders aus als erwartet.'
    else:
        result = 'fehler'
    undo = ({'action': 'conf-zurueck', 'params': {'backup': backup, 'nr': ''}} if backup and p['undo'] else None)
    with closing(db.connect()) as c, c:
        cur = c.execute('INSERT INTO changes (ts, client, host, vmid, ct_name, action, params, shell, rating, result,'
                        ' detail, undo, undo_of, backup) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (db.now(), client, host, int(p['vmid']), p['ct_name'], p['action'], json.dumps(p['params']),
                         p['shell'], p['rating'], result, detail, None, undo_of, before_text if backup else None))
        cid = cur.lastrowid
        if undo:  # auch nach einem Fehler mitten drin: was geändert wurde, lässt sich zurückspielen
            undo['params']['nr'] = str(cid)
            c.execute('UPDATE changes SET undo = ? WHERE id = ?', (json.dumps(undo), cid))
        if undo_of and result == 'ok':
            c.execute('UPDATE changes SET undone_by = ? WHERE id = ?', (cid, undo_of))
    db.audit('host-aenderung', target=f'CT {p["vmid"]}', result=result, client=client, befehl=p['shell'], nr=cid)
    return cid
