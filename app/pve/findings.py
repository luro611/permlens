"""Befunde (AP 2.3) und Empfehlungen (AP 2.5): typische Rechte-Probleme aus einem Scan erkennen.

Jeder Befund: {level, key, vmid, source, title, text, advice}
- level: 'problem' (geht nicht), 'hinweis' (geht, ist aber riskant oder wackelig), 'info' (gut zu wissen)
- title, text: (deutscher Text mit §, Werte …), werden in der Vorlage übersetzt
- advice: Liste {text, cmd, where, risk}; where 'host' oder 'ct' (im Container), risk 'harmlos' | 'vorsicht' | 'risiko'.
  PermLens führt in Phase 2 nichts aus, die Befehle sind nur zum Kopieren."""
from . import mapping as M
from .scan import mapping as mapping_kind
from .view import is_person

LEVELS = ('problem', 'hinweis', 'info')
SYSTEM_MAX = 999


def advice(text, *args, cmd='', where='', risk='', act=None, link=''):
    """act: dieselbe Empfehlung als Änderung, die PermLens selbst ausführen kann (Phase 3), z. B.
    {'action': 'rechte', 'path': '/mnt/x', 'add': 'g+w'}."""
    return {'text': (text, *args), 'cmd': cmd, 'where': where, 'risk': risk, 'act': act, 'link': link}


def _setgid(st):
    try:
        return bool(int(st.get('octal') or '0', 8) & 0o2000)
    except ValueError:
        return False


def idmap_lines(uid, gid):
    """lxc.idmap-Zeilen, die genau uid und gid 1:1 durchreichen und den Rest wie Proxmox verschieben."""
    out = []
    for kind, n in (('u', uid), ('g', gid)):
        out.append(f'lxc.idmap: {kind} 0 100000 {n}')
        out.append(f'lxc.idmap: {kind} {n} {n} 1')
        out.append(f'lxc.idmap: {kind} {n + 1} {100000 + n + 1} {65535 - n}')
    return '\n'.join(out)


def _subid_has(entries, n):
    return any(e['user'] == 'root' and e['start'] <= n < e['start'] + e['count'] for e in entries or [])


def nobody_advice(vmid, source, host_uid, host_gid, shared, hi):
    """Empfehlungen, wenn ein unprivilegierter Container einen Host-Ordner als nobody sieht."""
    out = []
    if 0 < host_uid < 65535 and 0 < host_gid < 65535:
        missing = [f'{f}: root:{n}:1' for f, n, key in (('/etc/subuid', host_uid, 'subuid'), ('/etc/subgid', host_gid, 'subgid'))
                   if not _subid_has(hi.get(key), n)]
        out.append(advice('Mapping einrichten: Nummer § (Besitzer) und Gruppe § an den Container durchreichen. '
                          'In /etc/pve/lxc/§.conf eintragen, dann den Container neu starten. '
                          'Dateien, die root im Container schon angelegt hat, gehören danach anderen Nummern.',
                          host_uid, host_gid, vmid,
                          cmd=idmap_lines(host_uid, host_gid) + ('\n\n# ' + '\n# '.join(missing) if missing else ''),
                          where='host', risk='risiko', link=f'/mapping?art=bestehend&ct={vmid}#vorschlag'))
    if not shared:
        out.append(advice('Oder den Ordner auf dem Host dem Container geben: Er gehört dann im Container root, '
                          'auf dem Host 100000. Nur sinnvoll, wenn kein anderer Container ihn nutzt.',
                          cmd=f'chown 100000:100000 {source}', where='host', risk='vorsicht'))
    return out


def collect(scan):
    """Alle Befunde eines Scans, Probleme zuerst."""
    if not scan:
        return []
    hi = scan.get('host_info') or {}
    host_user = {e['uid']: e['name'] for e in hi.get('passwd') or []}
    lxcs = [g for g in scan.get('guests', []) if g['type'] == 'lxc' and g.get('config')]
    users_of = {}  # Quelle → Container
    for g in lxcs:
        for m in g['config'].get('mounts', []):
            if m['kind'] == 'bind':
                users_of.setdefault(m['source'], []).append(g)
    out = []

    for g in lxcs:
        cfg, det, vmid = g['config'], g.get('details') or {}, g['vmid']
        ur, gr = M.ranges(cfg, 'u'), M.ranges(cfg, 'g')
        binds = [m for m in cfg.get('mounts', []) if m['kind'] == 'bind']
        for m in binds:
            hs = m.get('host_stat')
            if m.get('fs_kind') == 'fehlt':
                out.append({'level': 'problem', 'key': 'fehlt', 'vmid': vmid, 'source': m['source'],
                            'title': ('Mount-Quelle fehlt: §', m['source']),
                            'text': ('§ (§) soll § nach § einhängen, den Ordner gibt es auf dem Host aber nicht. '
                                     'Der Container bekommt dort nur einen leeren Ordner oder startet nicht.',
                                     g['name'], vmid, m['source'], m['target']),
                            'advice': [advice('Pfad prüfen (Tippfehler, Speicher nicht eingehängt?) oder den Mount entfernen. '
                                              'Die Daten auf anderen Speichern bleiben unberührt.',
                                              cmd=f'pct set {vmid} --delete {m["key"]}', where='host', risk='vorsicht')]})
                continue
            if m.get('fs_kind') == 'offline':
                out.append({'level': 'info', 'key': 'offline', 'vmid': vmid, 'source': m['source'],
                            'title': ('Keine Antwort: §', m['source']),
                            'text': ('Der Ordner hat beim Einlesen nicht geantwortet. Meist ist das NAS ausgeschaltet. '
                                     'Das ist kein Fehler im Container.',),
                            'advice': []})
                continue
            if not hs:
                continue
            if cfg.get('unprivileged') and (M.to_ct(ur, hs['uid']) is None or M.to_ct(gr, hs['gid']) is None):
                shared = len(users_of.get(m['source'], [])) > 1
                adv = nobody_advice(vmid, m['source'], hs['uid'], hs['gid'], shared, hi)
                out.append({'level': 'problem', 'key': 'nobody', 'vmid': vmid, 'source': m['source'],
                            'title': ('§ sieht § als nobody', g['name'], m['target']),
                            'text': ('Der Ordner gehört auf dem Host §:§. Diese Nummern sind im unprivilegierten Container '
                                     'nicht abgebildet. Schreiben geht dann nur, wenn die Rechte für „andere“ es erlauben, auch für root.',
                                     hs['uid'], hs['gid']),
                            'advice': adv})
            if m.get('fs_kind') == 'nfs':
                out.append({'level': 'info', 'key': 'nfs', 'vmid': vmid, 'source': m['source'],
                            'title': ('NFS: § in §', m['target'], g['name']),
                            'text': ('Bei NFS zählt die Nummer, nicht der Name. Das NAS entscheidet selbst und kann trotz '
                                     'passender Rechte ablehnen (z. B. root_squash oder eigene Rechte-Listen). '
                                     'Beim NAS kommt die Nummer an, die der Container auf dem Host hat (siehe Mapping).',),
                            'advice': [advice('Die Lösung liegt auf dem NAS (Squash-Regel oder Rechte für diese Nummer). '
                                              'PermLens verwaltet kein NAS.')]})
            if m.get('fs_kind') == 'smb':
                opts = (m.get('fs') or {}).get('options', '')
                out.append({'level': 'info', 'key': 'smb', 'vmid': vmid, 'source': m['source'],
                            'title': ('SMB: § in §', m['target'], g['name']),
                            'text': ('Bei SMB kommen Besitzer und Rechte aus den Mount-Optionen auf dem Host (§). '
                                     'chown und chmod wirken dort nicht.', opts),
                            'advice': [advice('Besitzer ändern über die Mount-Optionen uid=, gid=, file_mode=, dir_mode= '
                                              '(Speicher bzw. /etc/fstab auf dem Host).')]})
        users = {u['name']: u for u in det.get('users', [])}
        for sh in ((det.get('samba') or {}).get('shares') or []):
            fu = sh.get('force user')
            if fu and sh['name'].lower() != 'homes':
                u = users.get(fu)
                out.append({'level': 'info', 'key': 'samba', 'vmid': vmid, 'source': '',
                            'title': ('Freigabe [§] schreibt immer als §', sh['name'], fu),
                            'text': ('Über die Samba-Freigabe [§] in § gehört alles Neue § (Nummer §), egal wer sich am Mac '
                                     'oder PC anmeldet. Darum zählt dort nicht die Nummer des Macs.',
                                     sh['name'], g['name'], fu, u['uid'] if u else '?'),
                            'advice': []})
        for e in det.get('exports') or []:
            for c in e['clients']:
                if c['options'].get('no_root_squash'):
                    out.append({'level': 'hinweis', 'key': 'no_root_squash', 'vmid': vmid, 'source': '',
                                'title': ('NFS-Freigabe § erlaubt root (no_root_squash)', e['path']),
                                'text': ('In § darf root von § als root schreiben. Wer dort root ist, kann alle Dateien '
                                         'der Freigabe ändern.', g['name'], c['host']),
                                'advice': [advice('no_root_squash entfernen, wenn es nicht nötig ist. Danach exportfs -ra.',
                                                  where='ct', risk='vorsicht')]})
        if not cfg.get('unprivileged') and binds:
            out.append({'level': 'hinweis', 'key': 'privilegiert', 'vmid': vmid, 'source': '',
                        'title': ('§ ist privilegiert und hat Host-Ordner eingehängt', g['name']),
                        'text': ('root im Container ist root auf dem Host. Das löst Rechte-Probleme bequem, '
                                 'schottet den Container aber schwächer ab. Betroffen: §.',
                                 ', '.join(m['source'] for m in binds)),
                        'advice': [advice('Auf unprivilegiert mit eigenem Mapping umsteigen. '
                                          'Der Mapping-Assistent kommt mit Phase 4.', risk='risiko')]})

    # Gemeinsam genutzte Ordner ohne setgid
    for source, gs in users_of.items():
        m0 = next(m for m in gs[0]['config']['mounts'] if m['source'] == source)
        hs = m0.get('host_stat')
        if len(gs) > 1 and hs and 'directory' in (hs.get('type') or 'directory') and not _setgid(hs):
            out.append({'level': 'hinweis', 'key': 'setgid', 'vmid': None, 'source': source,
                        'title': ('Gemeinsamer Ordner ohne setgid: §', source),
                        'text': ('§ Container nutzen diesen Ordner. Ohne setgid-Bit bekommen neue Dateien die Gruppe '
                                 'dessen, der sie anlegt, und die anderen können sie oft nicht ändern.', len(gs)),
                        'advice': [advice('setgid-Bit setzen: Neue Dateien und Ordner erben dann die Gruppe § des Ordners. '
                                          'Bestehende Dateien bleiben, wie sie sind.', hs['gid'],
                                          cmd=f'chmod g+s {source}', where='host', risk='vorsicht')]})

    # Gleiche Nummer, verschiedene Namen (nur Nummern, denen gemeinsame Daten gehören)
    owners = {}
    for source, gs in users_of.items():
        m0 = next(m for m in gs[0]['config']['mounts'] if m['source'] == source)
        if m0.get('host_stat') and m0['host_stat']['uid'] > SYSTEM_MAX:
            owners.setdefault(m0['host_stat']['uid'], set()).add(source)
    for uid, sources in sorted(owners.items()):
        names = [('Host', host_user[uid])] if uid in host_user else []
        for g in lxcs:
            ur = M.ranges(g['config'], 'u')
            for u in (g.get('details') or {}).get('users', []):
                if M.to_host(ur, u['uid']) == uid:
                    names.append((str(g['vmid']), u['name']))
        if len({n for _, n in names}) > 1:
            out.append({'level': 'info', 'key': 'uid-namen', 'vmid': None, 'source': '',
                        'title': ('Nummer § hat verschiedene Namen', uid),
                        'text': ('Der Nummer § gehören §. So heißt sie: §. Für die Rechte zählt nur die Nummer.',
                                 uid, ', '.join(sorted(sources)), ', '.join(f'{w} {n}' for w, n in names)),
                        'advice': []})

    # Gleicher Name, verschiedene Nummern (Host und Container)
    by_name = {}
    for u in hi.get('passwd') or []:
        if is_person(u['uid']):
            by_name.setdefault(u['name'], []).append(('Host', u['uid'], u['uid']))
    for g in lxcs:
        ur = M.ranges(g['config'], 'u')
        for u in (g.get('details') or {}).get('users', []):
            if is_person(u['uid']):
                by_name.setdefault(u['name'], []).append((g['vmid'], u['uid'], M.to_host(ur, u['uid'])))
    for name, rows in sorted(by_name.items()):
        if len({h for _, _, h in rows}) > 1:
            out.append({'level': 'hinweis', 'key': 'name-uid', 'vmid': None, 'source': '',
                        'title': ('„§“ hat verschiedene Nummern', name),
                        'text': ('Gleicher Name, aber verschiedene Nummern auf dem Host: §. Dateien von „§“ aus einem '
                                 'Container gehören für die anderen jemand anderem.',
                                 ', '.join(f'{v}: {c} → {h if h is not None else "–"}' for v, c, h in rows), name),
                        'advice': []})

    # Ungenutzte Einträge in /etc/subuid und /etc/subgid
    for key in ('subuid', 'subgid'):
        unused = sorted({e['user'] for e in hi.get(key) or [] if e['user'] != 'root'})
        if unused:
            out.append({'level': 'info', 'key': key, 'vmid': None, 'source': '',
                        'title': ('Ungenutzte Einträge in /etc/§', key),
                        'text': ('Einträge für §. Container auf Proxmox nutzen nur die Einträge von root, '
                                 'diese hier verwendet kein Container.', ', '.join(unused)),
                        'advice': []})

    out.sort(key=lambda f: (LEVELS.index(f['level']), f['vmid'] or 0))
    return out


def counts(found):
    return {lv: sum(1 for f in found if f['level'] == lv) for lv in LEVELS}


def for_diagnose(scan, guest, user, path, res):
    """Empfehlungen für ein „nein“ auf der Diagnose-Seite."""
    from .view import mount_for
    if not res or (res['read'] and res['write']):
        return []
    cfg, det, vmid = guest.get('config') or {}, guest.get('details') or {}, guest['vmid']
    m = mount_for(cfg, path)
    if res['cause'] == 'nobody' and m and m.get('host_stat'):
        hs = m['host_stat']
        shared = sum(1 for g in (scan or {}).get('guests', []) if g['type'] == 'lxc'
                     for x in (g.get('config') or {}).get('mounts', []) if x['source'] == m['source']) > 1
        return nobody_advice(vmid, m['source'], hs['uid'], hs['gid'], shared, (scan or {}).get('host_info') or {})
    if res['cause'] == 'nur-lesen':
        return [advice('Der Mount ist schreibgeschützt eingetragen. Wenn Schreiben gewollt ist: '
                       'in /etc/pve/lxc/§.conf bei § „ro=1“ entfernen und den Container neu starten.',
                       vmid, m['key'] if m else 'mpN', where='host', risk='vorsicht')]
    if res['cause'] == 'weg':
        bad = next((s for s in res['steps'] if not s['ok']), None)
        return [advice('Hineingehen für alle erlauben (nur x, die Liste der Dateien bleibt geschützt):',
                       cmd=f'chmod o+x {bad["path"]}', where='ct', risk='vorsicht',
                       act={'action': 'rechte', 'path': bad['path'], 'add': 'o+x'})] if bad else []
    if res['cause'] == 'rechte':
        st = (det.get('stat') or {}).get(path) or {}
        grp = next((g for g in det.get('groups', []) if g['gid'] == st.get('gid')), None)
        in_group = st.get('gid') == user['gid'] or bool(grp and user['name'] in grp['members'])
        out = []
        if grp and not in_group and user['uid'] != 0:
            out.append(advice('Benutzer § in die Gruppe § des Ordners aufnehmen. Wirkt ab der nächsten Anmeldung '
                              'bzw. nach Neustart des Dienstes.', user['name'], grp['name'],
                              cmd=f'usermod -aG {grp["name"]} {user["name"]}', where='ct', risk='vorsicht',
                              act={'action': 'mitglied-hinzu', 'user': user['name'], 'group': grp['name']}))
        try:
            mode = int(st.get('octal') or '0', 8)
        except ValueError:
            mode = 0
        if st and not mode & 0o020 and st.get('uid') != user['uid']:
            out.append(advice('Der Gruppe des Ordners Schreiben erlauben:', cmd=f'chmod g+w {path}', where='ct',
                              risk='vorsicht', act={'action': 'rechte', 'path': path, 'add': 'g+w'}))
        out.append(advice('Nicht empfohlen: chmod 777 öffnet den Ordner für jeden.', risk='risiko'))
        return out
    return []
