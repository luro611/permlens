"""Mapping-Assistent (Phase 4, AP 4.2): Bauplan für einen neuen unprivilegierten Container.

Eingabe: Host-Ordner, die in den Container sollen, und als wer dort geschrieben wird (meist der Besitzer des
Ordners auf dem Host). Ausgabe: Zeilen für /etc/pve/lxc/<Nr>.conf (mpN, lxc.idmap), fehlende Zeilen für
/etc/subuid und /etc/subgid, Werte für den Docker-Stack und eine Schritt-für-Schritt-Liste. PermLens ändert dabei
nichts am Host, alles ist zum Kopieren (Entscheidung Lutz, 2026-10-21).

Texte für die Oberfläche stehen als Tupel (deutscher Text mit §, Werte …) und werden in der Vorlage übersetzt."""
import re
import shlex

from . import access, mapping as M

PATH = re.compile(r'^/[A-Za-z0-9._@+:=~/-]*$')  # ohne Leerzeichen und Komma: steht so in der mpN-Zeile
APPS = {
    'paperless': {'label': 'paperless-ngx', 'uid': 'USERMAP_UID', 'gid': 'USERMAP_GID'},
    'docker': {'label': 'Docker-App (z. B. linuxserver.io)', 'uid': 'PUID', 'gid': 'PGID'},
    'ohne': {'label': 'ohne Docker', 'uid': '', 'gid': ''},
}
MAX_FOLDERS = 4


def _path_ok(p):
    return bool(PATH.match(p or '')) and '/../' not in p + '/' and '/./' not in p + '/' and p != '/'


def known_folders(scan):
    """Host-Ordner, die PermLens kennt (Bind-Mount-Quellen bestehender Container), mit Besitzer und Rechten."""
    out = {}
    for g in (scan or {}).get('guests', []):
        for m in ((g.get('config') or {}).get('mounts') or []):
            if m.get('kind') != 'bind' or not m.get('source', '').startswith('/'):
                continue
            f = out.setdefault(m['source'], {'path': m['source'], 'stat': m.get('host_stat'), 'used': []})
            f['stat'] = f['stat'] or m.get('host_stat')
            f['used'].append(g['vmid'])
    return sorted(out.values(), key=lambda f: f['path'])


def _num(text):
    text = str(text or '').strip()
    return int(text) if text.isdigit() else None


def make(scan, params):
    """Bauplan aus den Formularwerten. Gibt {'errors': [...], …} zurück; ohne Fehler auch 'text' und 'steps'."""
    hi = (scan or {}).get('host_info') or {}
    known = {f['path']: f for f in known_folders(scan)}
    errors = []
    vmid = str(params.get('vmid', '')).strip()
    if vmid and not re.match(r'^[1-9][0-9]{2,8}$', vmid):
        errors.append(('Die Container-Nummer ist ungültig (100 bis 999999999).',))
    if vmid and any(str(g['vmid']) == vmid for g in (scan or {}).get('guests', [])):
        errors.append(('Container § gibt es schon. Der Bauplan ist für einen neuen Container; für bestehende kommt ein eigener Vorschlag.', vmid))
    nr = vmid or '<Nr>'

    folders = []
    for i in range(MAX_FOLDERS):
        src = str(params.get(f'src{i}', '')).strip().rstrip('/')
        if not src:
            continue
        dst = str(params.get(f'dst{i}', '')).strip().rstrip('/') or src
        if not _path_ok(src) or not _path_ok(dst):
            errors.append(('Ordner § bzw. Ziel § ist ungültig: absoluter Pfad ohne Leerzeichen, Komma und „..“.', src, dst))
            continue
        folders.append({'src': src, 'dst': dst, 'ro': bool(params.get(f'ro{i}')), 'stat': (known.get(src) or {}).get('stat'),
                        'used': (known.get(src) or {}).get('used', [])})
    if not folders:
        errors.append(('Mindestens einen Host-Ordner angeben.',))
    if len({f['dst'] for f in folders}) != len(folders):
        errors.append(('Zwei Ordner haben dasselbe Ziel im Container.',))

    # Als wer wird geschrieben? Ohne Angabe: Besitzer des ersten bekannten Ordners
    first = next((f['stat'] for f in folders if f['stat']), None)
    uid = _num(params.get('uid')) if str(params.get('uid', '')).strip() else (first or {}).get('uid')
    gid = _num(params.get('gid')) if str(params.get('gid', '')).strip() else (first or {}).get('gid')
    extra = [_num(x) for x in re.split(r'[,\s]+', str(params.get('gids', '')).strip()) if x]
    if uid is None or gid is None:
        errors.append(('Als wer soll geschrieben werden? Benutzer- und Gruppennummer angeben (der Besitzer des Ordners ist PermLens nicht bekannt).',))
    elif not (M.PASS_MIN <= uid <= M.PASS_MAX and M.PASS_MIN <= gid <= M.PASS_MAX):
        errors.append(('Durchgereicht werden nur Nummern von 1 bis 65533. Gehört der Ordner root (0), braucht es kein eigenes Mapping: dann den Ordner auf dem Host 100000 geben.',))
    if any(x is None or not M.PASS_MIN <= x <= M.PASS_MAX for x in extra):
        errors.append(('Weitere Gruppen als Nummern von 1 bis 65533 angeben, mit Komma getrennt.',))
    app = params.get('app') if params.get('app') in APPS else 'paperless'
    out = {'errors': errors, 'folders': folders, 'uid': uid, 'gid': gid, 'extra': extra, 'app': app, 'vmid': vmid}
    if errors:
        return out

    gids = sorted({gid, *extra})
    ru, rg = M.plan_ranges([uid]), M.plan_ranges(gids)
    idmap = M.idmap_text([uid], gids)
    mps = [f"mp{i}: {f['src']},mp={f['dst']}" + (',ro=1' if f['ro'] else '') for i, f in enumerate(folders)]
    sub_u, sub_g = M.subid_missing(ru, hi.get('subuid')), M.subid_missing(rg, hi.get('subgid'))
    a = APPS[app]
    env = [f"{a['uid']}={uid}", f"{a['gid']}={gid}"] if a['uid'] else []

    # Was der Container danach in jedem Ordner darf (Rechte-Rechner aus Phase 2, ohne ACLs)
    user = {'uid': uid, 'gid': gid, 'gids': extra}
    for f in folders:
        st = f['stat']
        if not st:
            f['check'] = None
            continue
        ct = {**st, 'uid': M.to_ct(ru, st['uid']) if M.to_ct(ru, st['uid']) is not None else M.NOBODY,
              'gid': M.to_ct(rg, st['gid']) if M.to_ct(rg, st['gid']) is not None else M.NOBODY}
        f['ct_owner'] = (ct['uid'], ct['gid'])
        f['check'] = {'read': access.allowed(user, ct, None, 'rx' if access.is_dir(ct) else 'r', True)[0],
                      'write': access.allowed(user, ct, None, 'wx' if access.is_dir(ct) else 'w', True)[0] and not f['ro']}

    conf = mps + idmap
    shared = {}
    for kind, hits in (('Benutzer', M.shared_with(scan, 'u', [uid])), ('Gruppe', M.shared_with(scan, 'g', gids))):
        for h in hits:  # eine Zeile je Container: „Benutzer 1000, Gruppe 1000“
            s = shared.setdefault(h['vmid'], {'vmid': h['vmid'], 'name': h['name'], 'privileged': h['privileged'], 'ids': []})
            s['ids'].append(f"{kind} {h['id']}")
    shared = [dict(s, ids=', '.join(s['ids'])) for s in shared.values()]
    cmds = {
        'subuid': ' && '.join(f"(grep -qx '{x}' /etc/subuid || echo '{x}' >> /etc/subuid)" for x in sub_u),
        'subgid': ' && '.join(f"(grep -qx '{x}' /etc/subgid || echo '{x}' >> /etc/subgid)" for x in sub_g),
        'conf': f"cat >> /etc/pve/lxc/{nr}.conf <<'EOF'\n" + '\n'.join(conf) + '\nEOF',
    }
    text = '\n'.join(
        [f'# PermLens-Bauplan für einen neuen unprivilegierten Container ({nr})',
         f'# Schreiben als Benutzer {uid}, Gruppe {gid}' + (f", weitere Gruppen {', '.join(map(str, extra))}" if extra else ''),
         '', f'# 1) Zeilen für /etc/pve/lxc/{nr}.conf (Container gestoppt)'] + conf +
        ['', '# 2) Zeilen für /etc/subuid und /etc/subgid (nur falls noch nicht vorhanden)'] +
        ([f'# /etc/subuid: {x}' for x in sub_u] + [f'# /etc/subgid: {x}' for x in sub_g] or ['# nichts zu ergänzen']) +
        ([''] + [f"# 3) Für den Docker-Stack ({a['label']})"] + env if env else []) + [''])
    out.update(idmap=idmap, mps=mps, conf=conf, sub_u=sub_u, sub_g=sub_g, env=env, app_label=a['label'],
               shared=shared, cmds=cmds, text=text, nr=nr,
               useradd=f"getent group {gid} >/dev/null || groupadd -g {gid} app; "
                       + shlex.join(['useradd', '-m', '-u', str(uid), '-g', str(gid), 'app']))
    return out


# ---------------------------------------------------------------- AP 4.3: bestehender Container
def _passed(cfg, kind):
    """Nummern, die das bisherige Mapping 1:1 durchreicht."""
    return sorted({n for r in M.passthrough(M.ranges(cfg, kind)) for n in range(r['ct'], r['ct'] + r['count'])})


def _standard_rest(cfg, kind):
    """True, wenn alle übrigen Bereiche wie bei Proxmox um 100000 verschoben sind (dann ersetzt der Vorschlag nur)."""
    return all(r['host'] in (r['ct'], M.BASE + r['ct']) for r in M.ranges(cfg, kind) or [])


def existing_plan(scan, vmid, params):
    """Vorschlag für einen bestehenden unprivilegierten Container: welche Nummern zusätzlich durchreichen,
    neue lxc.idmap-Zeilen, was mit vorhandenen Dateien passiert und die Befehle in der richtigen Reihenfolge."""
    hi = (scan or {}).get('host_info') or {}
    g = next((x for x in (scan or {}).get('guests', []) if x['vmid'] == vmid and x['type'] == 'lxc'), None)
    out = {'errors': [], 'vmid': vmid, 'guest': g}
    if not g or not g.get('config'):
        out['errors'].append(('Diesen Container gibt es nicht.',))
        return out
    cfg = g['config']
    if not cfg.get('unprivileged'):
        out['errors'].append(('Container § ist privilegiert. Er sieht die Nummern des Hosts ohnehin 1:1. Für den Umstieg auf unprivilegiert gibt es den Reiter „Privilegiert → unprivilegiert“.', vmid))
        return out
    ru, rg = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
    mounts = []
    for m in cfg.get('mounts', []):
        if m.get('kind') != 'bind':
            continue
        st = m.get('host_stat')
        mounts.append({'src': m['source'], 'dst': m['target'], 'key': m.get('key', ''), 'stat': st,
                       'ct_now': (M.to_ct(ru, st['uid']), M.to_ct(rg, st['gid'])) if st else None})
    # Vorschlag: was schon durchgereicht wird, plus Besitzer und Gruppe der Ordner, die heute nobody erscheinen
    cand_u = {st['uid'] for m in mounts if (st := m['stat']) and M.to_ct(ru, st['uid']) is None and M.PASS_MIN <= st['uid'] <= M.PASS_MAX}
    cand_g = {st['gid'] for m in mounts if (st := m['stat']) and M.to_ct(rg, st['gid']) is None and M.PASS_MIN <= st['gid'] <= M.PASS_MAX}
    now_u, now_g = _passed(cfg, 'u'), _passed(cfg, 'g')
    # params: {'chosen': '1', 'u': [...], 'g': [...], 'more_u': '…', 'more_g': '…'}; ohne 'chosen' gilt der Vorschlag
    chosen = params.get('chosen') == '1'
    sel_u = {int(x) for x in params.get('u') or [] if str(x).isdigit()} if chosen else set(cand_u)
    sel_g = {int(x) for x in params.get('g') or [] if str(x).isdigit()} if chosen else set(cand_g)
    for key, sel in (('more_u', sel_u), ('more_g', sel_g)):
        for x in re.split(r'[,\s]+', str(params.get(key, '') or '').strip()):
            if x:
                if not x.isdigit() or not M.PASS_MIN <= int(x) <= M.PASS_MAX:
                    out['errors'].append(('Zusätzliche Nummern von 1 bis 65533 angeben, mit Komma getrennt.',))
                else:
                    sel.add(int(x))
    out.update(mounts=mounts, cand_u=sorted(cand_u | sel_u), cand_g=sorted(cand_g | sel_g), sel_u=sel_u, sel_g=sel_g,
               now_u=now_u, now_g=now_g, standard=_standard_rest(cfg, 'u') and _standard_rest(cfg, 'g'))
    new_u, new_g = sorted(set(now_u) | sel_u), sorted(set(now_g) | sel_g)
    added_u, added_g = [n for n in new_u if n not in now_u], [n for n in new_g if n not in now_g]
    if out['errors']:
        return out
    if not added_u and not added_g:
        out['nothing'] = True
        return out
    nu, ng = M.plan_ranges(new_u), M.plan_ranges(new_g)
    idmap = M.idmap_text(new_u, new_g)
    for m in mounts:  # danach im Container
        st = m['stat']
        if st:
            ct = {**st, 'uid': M.to_ct(nu, st['uid']) if M.to_ct(nu, st['uid']) is not None else M.NOBODY,
                  'gid': M.to_ct(ng, st['gid']) if M.to_ct(ng, st['gid']) is not None else M.NOBODY}
            m['ct_after'] = (ct['uid'], ct['gid'])
    # Dateien, die heute einer verschobenen Nummer gehören (Host 100000+N), sehen danach nobody: nachziehen
    users = {u['uid']: u['name'] for u in ((g.get('details') or {}).get('users') or [])}
    groups = {x['gid']: x['name'] for x in ((g.get('details') or {}).get('groups') or [])}
    moved = [('u', n, M.to_host(ru, n), users.get(n, '')) for n in added_u if M.to_host(ru, n) not in (None, n)] + \
            [('g', n, M.to_host(rg, n), groups.get(n, '')) for n in added_g if M.to_host(rg, n) not in (None, n)]
    conf = f'/etc/pve/lxc/{vmid}.conf'
    # pct mount hängt auch die Mount-Punkte ein. find -xdev steigt nicht hinein, würde aber den Einhängepunkt
    # selbst ändern (also den Ordner auf dem Host!). Deshalb werden die Ziele ausdrücklich übersprungen.
    root = f'/var/lib/lxc/{vmid}/rootfs'
    targets = [root + '/' + str(m.get('target') or m['dst']).strip('/') for m in cfg.get('mounts', []) if m.get('target')]
    prune = ('\\( ' + ' -o '.join(f'-path {shlex.quote(t)}' for t in targets) + ' \\) -prune -o ') if targets else ''
    fix, unfix = [], []
    for kind, n, old, name in moved:
        opt, tool = ('-uid', 'chown') if kind == 'u' else ('-gid', 'chgrp')
        fix.append(f'find {root} -xdev {prune}{opt} {old} -exec {tool} -h {n} {{}} +')
        fix += [f'find {shlex.quote(m["src"])} -xdev {opt} {old} -exec {tool} -h {n} {{}} +' for m in mounts]
        # Zurück nur im Container selbst: In den Host-Ordnern gehörten Dateien der Nummer N schon vorher N
        # (deshalb wird sie ja durchgereicht), dort ließe sich nicht unterscheiden, was nachgezogen wurde.
        unfix.append(f'find {root} -xdev {prune}{opt} {n} -exec {tool} -h {old} {{}} +')
    cmds = {
        'backup': f'cp {conf} /root/{vmid}.conf.vor-permlens',
        'stop': f'pct shutdown {vmid}',
        'subuid': ' && '.join(f"(grep -qx '{x}' /etc/subuid || echo '{x}' >> /etc/subuid)" for x in M.subid_missing(nu, hi.get('subuid'))),
        'subgid': ' && '.join(f"(grep -qx '{x}' /etc/subgid || echo '{x}' >> /etc/subgid)" for x in M.subid_missing(ng, hi.get('subgid'))),
        'conf': (f'awk -v add="$(cat <<\'EOF\'\n' + '\n'.join(idmap) + '\nEOF\n)" '
                 "'BEGIN{done=0} /^\\[/ && !done {print add; print \"\"; done=1} !(!done && /^lxc\\.idmap:/) {print} "
                 f"END{{if(!done) print add}}' /root/{vmid}.conf.vor-permlens > /root/{vmid}.conf.neu && "
                 f'cat /root/{vmid}.conf.neu > {conf}'),
        'fix': (f'pct mount {vmid}\n' + '\n'.join(fix) + f'\npct unmount {vmid}') if fix else '',
        'start': f'pct start {vmid}',
        'undo': (f'pct shutdown {vmid} && cat /root/{vmid}.conf.vor-permlens > {conf}'
                 + (f'\npct mount {vmid}\n' + '\n'.join(unfix) + f'\npct unmount {vmid}' if unfix else '')
                 + f'\npct start {vmid}'),
    }
    out.update(new_u=new_u, new_g=new_g, added_u=added_u, added_g=added_g, idmap=idmap, moved=moved, cmds=cmds,
               shared=[h for h in M.shared_with(scan, 'u', added_u, skip=vmid) + M.shared_with(scan, 'g', added_g, skip=vmid)])
    return out


# ---------------------------------------------------------------- AP 4.4: Umstieg privilegiert → unprivilegiert
def _idmap_cmd(vmid, idmap):
    """Nur die lxc.idmap-Zeilen des laufenden Stands austauschen (Snapshots bleiben); vorher Sicherung."""
    conf = f'/etc/pve/lxc/{vmid}.conf'
    return (f'cp {conf} /root/{vmid}.conf.vor-permlens && awk -v add="$(cat <<\'EOF\'\n' + '\n'.join(idmap) + '\nEOF\n)" '
            "'BEGIN{done=0} /^\\[/ && !done {print add; print \"\"; done=1} !(!done && /^lxc\\.idmap:/) {print} "
            f"END{{if(!done) print add}}' /root/{vmid}.conf.vor-permlens > /root/{vmid}.conf.neu && "
            f'cat /root/{vmid}.conf.neu > {conf}')


def _renumber_rootfs(vmid, cfg, moves):
    """Befehle: Dateien im Container-Dateisystem von Host-Nummer alt auf neu, Einhängepunkte übersprungen."""
    root = f'/var/lib/lxc/{vmid}/rootfs'
    targets = [root + '/' + str(m.get('target')).strip('/') for m in cfg.get('mounts', []) if m.get('target')]
    prune = ('\\( ' + ' -o '.join(f'-path {shlex.quote(t)}' for t in targets) + ' \\) -prune -o ') if targets else ''
    lines = [f'find {root} -xdev {prune}{"-uid" if k == "u" else "-gid"} {old} -exec {"chown" if k == "u" else "chgrp"} -h {new} {{}} +'
             for k, new, old in moves]
    return f'pct mount {vmid}\n' + '\n'.join(lines) + f'\npct unmount {vmid}' if lines else ''


def backup_storages(scan):
    """Speicher, auf denen Proxmox Sicherungen ablegen darf (content enthält backup)."""
    hi = (scan or {}).get('host_info') or {}
    return [s['id'] for s in hi.get('storage') or []
            if 'backup' in (s['props'].get('content') or '').split(',') and s['props'].get('disable') != '1']


def migration_plan(scan, vmid, params):
    """Anleitung für einen privilegierten Container: sichern, als neuer unprivilegierter Container wiederherstellen,
    Mapping für die eingehängten Ordner, prüfen, Weg zurück. Der alte Container bleibt bis zum Schluss erhalten."""
    hi = (scan or {}).get('host_info') or {}
    guests = (scan or {}).get('guests', [])
    g = next((x for x in guests if x['vmid'] == vmid and x['type'] == 'lxc'), None)
    out = {'errors': [], 'vmid': vmid, 'guest': g}
    if not g or not g.get('config'):
        out['errors'].append(('Diesen Container gibt es nicht.',))
        return out
    cfg = g['config']
    if cfg.get('unprivileged'):
        out['errors'].append(('Container § ist schon unprivilegiert. Für ihn gibt es den Reiter „Bestehender Container“.', vmid))
        return out
    used = {x['vmid'] for x in guests}
    new = str(params.get('new', '')).strip()
    if new:
        if not re.match(r'^[1-9][0-9]{2,8}$', new):
            out['errors'].append(('Die neue Container-Nummer ist ungültig (100 bis 999999999).',))
        elif int(new) in used:
            out['errors'].append(('Die Nummer § ist schon vergeben.', new))
    else:
        n = vmid + 100
        while n in used:
            n += 1
        new = str(n)
    stores = backup_storages(scan)
    store = params.get('store') if params.get('store') in stores else (stores[0] if stores else '')
    if not store:
        out['errors'].append(('Auf diesem Proxmox ist kein Speicher für Sicherungen eingetragen (content backup).',))
    rootfs = str((cfg.get('raw') or {}).get('rootfs', '')).split(':', 1)[0] or 'local-lvm'
    mounts = [{'src': m['source'], 'dst': m['target'], 'stat': m.get('host_stat')}
              for m in cfg.get('mounts', []) if m.get('kind') == 'bind']
    cand_u = {m['stat']['uid'] for m in mounts if m['stat'] and M.PASS_MIN <= m['stat']['uid'] <= M.PASS_MAX}
    cand_g = {m['stat']['gid'] for m in mounts if m['stat'] and M.PASS_MIN <= m['stat']['gid'] <= M.PASS_MAX}
    chosen = params.get('chosen') == '1'
    sel_u = {int(x) for x in params.get('u') or [] if str(x).isdigit()} if chosen else set(cand_u)
    sel_g = {int(x) for x in params.get('g') or [] if str(x).isdigit()} if chosen else set(cand_g)
    for key, sel in (('more_u', sel_u), ('more_g', sel_g)):
        for x in re.split(r'[,\s]+', str(params.get(key, '') or '').strip()):
            if x:
                if not x.isdigit() or not M.PASS_MIN <= int(x) <= M.PASS_MAX:
                    out['errors'].append(('Zusätzliche Nummern von 1 bis 65533 angeben, mit Komma getrennt.',))
                else:
                    sel.add(int(x))
    out.update(new=new, stores=stores, store=store, mounts=mounts, cand_u=sorted(cand_u | sel_u), cand_g=sorted(cand_g | sel_g),
               sel_u=sel_u, sel_g=sel_g, root_owned=[m for m in mounts if m['stat'] and (m['stat']['uid'] == 0 or m['stat']['gid'] == 0)])
    if out['errors']:
        return out
    nu, ng = M.plan_ranges(sorted(sel_u)), M.plan_ranges(sorted(sel_g))
    for m in mounts:
        st = m['stat']
        if st:
            m['ct_after'] = (M.to_ct(nu, st['uid']) if M.to_ct(nu, st['uid']) is not None else M.NOBODY,
                             M.to_ct(ng, st['gid']) if M.to_ct(ng, st['gid']) is not None else M.NOBODY)
    idmap = M.idmap_text(sorted(sel_u), sorted(sel_g)) if sel_u or sel_g else []
    # Proxmox verschiebt beim Wiederherstellen alles um 100000; durchgereichte Nummern müssen zurück auf N
    moves = [('u', n, M.BASE + n) for n in sorted(sel_u)] + [('g', n, M.BASE + n) for n in sorted(sel_g)]
    features = str((cfg.get('raw') or {}).get('features', ''))
    vol = f"VOL=$(pvesm list {store} --vmid {vmid} --content backup | awk 'NR>1{{print $1}}' | sort | tail -1) && echo \"$VOL\""
    cmds = {
        'backup': f'vzdump {vmid} --storage {store} --mode stop --compress zstd',
        'old_off': f'pct shutdown {vmid} && pct set {vmid} --onboot 0',
        'restore': f'{vol} && pct restore {new} "$VOL" --unprivileged 1 --storage {rootfs} --ignore-unpack-errors 1',
        'subuid': ' && '.join(f"(grep -qx '{x}' /etc/subuid || echo '{x}' >> /etc/subuid)" for x in M.subid_missing(nu, hi.get('subuid'))) if sel_u else '',
        'subgid': ' && '.join(f"(grep -qx '{x}' /etc/subgid || echo '{x}' >> /etc/subgid)" for x in M.subid_missing(ng, hi.get('subgid'))) if sel_g else '',
        'idmap': _idmap_cmd(new, idmap) if idmap else '',
        'fix': _renumber_rootfs(new, cfg, moves),
        'docker': '' if 'keyctl' in features else f'pct set {new} --features nesting=1,keyctl=1',
        'start': f'pct start {new} && pct set {new} --onboot 1',
        'finish': f'pct destroy {vmid}',
        'back': f'pct shutdown {new} && pct set {new} --onboot 0 && pct set {vmid} --onboot 1 && pct start {vmid}',
    }
    out.update(idmap=idmap, cmds=cmds, moves=moves, rootfs=rootfs)
    return out
