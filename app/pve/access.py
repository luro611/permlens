"""Rechte-Rechner: Darf ein Benutzer im Container einen Ordner öffnen, lesen, beschreiben?

Gerechnet wird wie im Linux-Kern, aus Sicht des Containers (Nummern so, wie der Container sie sieht):

1. root darf alles, aber in einem unprivilegierten Container nur bei Dateien, deren Besitzer und Gruppe
   im Container abgebildet sind. Gehört etwas nobody, ist root dort ein ganz normaler „anderer“.
2. Besitzer → Rechte des Besitzers.
3. ACL-Eintrag für den Benutzer → dessen Rechte (begrenzt durch die Maske).
4. Gruppe: Hauptgruppe des Ordners oder ACL-Gruppe, in der der Benutzer ist → deren Rechte
   (mit ACL begrenzt durch die Maske). Passt eine Gruppe, aber keine erlaubt es: nein, „andere“ zählt nicht.
5. Sonst die Rechte für „andere“.

Auf dem Weg zum Ziel braucht jeder Ordner das Recht x (hineingehen). Zum Lesen eines Ordners braucht man
r und x, zum Anlegen von Dateien darin w und x. Ein schreibgeschützter Mount verbietet das Schreiben immer.

Texte sind deutsch mit § als Platzhalter und werden in der Vorlage übersetzt (wie bei ssh.explain)."""
from .mapping import NOBODY

BITS = {'r': 4, 'w': 2, 'x': 1}


def rwx(n):
    return ''.join(c if n & b else '-' for c, b in BITS.items())


def _mode(st):
    """Rechte als Zahl aus stat (%a, z. B. '2775')."""
    try:
        return int(st.get('octal') or '0', 8)
    except ValueError:
        return 0


def _bits(perm):
    """'r-x' → 5"""
    return sum(b for c, b in BITS.items() if c in (perm or ''))


def _has(n, want):
    return all(n & BITS[c] for c in want)


def is_dir(st):
    return 'directory' in (st.get('type') or '') or (st.get('mode') or '').startswith('d')


def unmapped(st, unprivileged):
    """Besitzer oder Gruppe sind im Container nicht abgebildet (erscheinen als nobody)."""
    return unprivileged and (st['uid'] == NOBODY or st['gid'] == NOBODY)


def allowed(user, st, acl, want, unprivileged=False):
    """Darf user (uid, gid, gids) auf dieser Datei/diesem Ordner `want` (z. B. 'wx')?
    Gibt (ja/nein, Grund) zurück, Grund als (Text, Werte …)."""
    mode = _mode(st)
    entries = (acl or {}).get('access') or []
    mask = next((_bits(e['perm']) for e in entries if e['tag'] == 'mask'), None)

    def masked(n):
        return n if mask is None else n & mask

    if user['uid'] == 0:
        if not unmapped(st, unprivileged):
            if 'x' in want and not is_dir(st) and not mode & 0o111:
                return False, ('root darf alles außer ausführen, hier ist kein x gesetzt',)
            return True, ('root darf alles',)
        # root im unprivilegierten Container: keine Sonderrechte, weiter wie ein normaler Benutzer

    if user['uid'] == st['uid']:
        n = (mode >> 6) & 7
        return _has(n, want), ('Besitzer (§): §', st['uid'], rwx(n))

    for e in entries:
        if e['tag'] == 'user' and e.get('id') == user['uid']:
            n = masked(_bits(e['perm']))
            return _has(n, want), ('ACL für den Benutzer: §', rwx(n))

    gids = {user['gid'], *user.get('gids', ())}
    group_obj = next((_bits(e['perm']) for e in entries if e['tag'] == 'group_obj'), (mode >> 3) & 7)
    matches = []
    if st['gid'] in gids:
        matches.append((masked(group_obj), ('Gruppe des Ordners (§): §', st['gid'])))
    for e in entries:
        if e['tag'] == 'group' and e.get('id') in gids:
            matches.append((masked(_bits(e['perm'])), ('ACL für Gruppe §: §', e['id'])))
    if matches:
        for n, (text, gid) in matches:
            if _has(n, want):
                return True, (text, gid, rwx(n))
        n, (text, gid) = matches[0]
        return False, (text, gid, rwx(n))

    n = mode & 7
    return _has(n, want), ('andere: §', rwx(n))


def check(user, chain, readonly=False, unprivileged=False, fs_kind=''):
    """Ganzen Weg prüfen. chain: Liste {path, stat, acl} von oben bis zum Ziel (Ziel zuletzt).

    Ergebnis: {enter, read, write, cause, steps, hints}
    - cause: warum es nicht geht ('fehlt', 'nobody', 'weg', 'rechte', 'nur-lesen') oder ''
      (view.diagnose ergänzt 'offline', wenn das NAS nicht antwortet)
    - steps: je Ordner {path, ok, need, why}
    - hints: zusätzliche Hinweise als (Text, Werte …)"""
    res = {'enter': False, 'read': False, 'write': False, 'cause': '', 'steps': [], 'hints': []}
    if not chain or not chain[-1].get('stat'):
        res['cause'] = 'fehlt'
        return res
    *parents, target = chain

    for p in parents:
        st = p.get('stat')
        if not st:  # nicht eingelesen: nichts behaupten
            continue
        ok, why = allowed(user, st, p.get('acl'), 'x', unprivileged)
        res['steps'].append({'path': p['path'], 'ok': ok, 'need': 'x', 'why': why})
        if not ok:
            res['cause'] = 'nobody' if unmapped(st, unprivileged) else 'weg'
            return res

    st, acl = target['stat'], target.get('acl')
    folder = is_dir(st)
    res['enter'] = allowed(user, st, acl, 'x', unprivileged)[0] if folder else True
    ok_r, why_r = allowed(user, st, acl, 'rx' if folder else 'r', unprivileged)
    ok_w, why_w = allowed(user, st, acl, 'wx' if folder else 'w', unprivileged)
    res['read'] = ok_r
    res['write'] = ok_w and not readonly
    res['steps'].append({'path': target['path'], 'ok': ok_r, 'need': 'rx' if folder else 'r', 'why': why_r})
    res['steps'].append({'path': target['path'], 'ok': ok_w, 'need': 'wx' if folder else 'w', 'why': why_w})
    if readonly and ok_w:
        res['hints'].append(('Der Ordner ist schreibgeschützt eingehängt (ro).',))
    if not (ok_r and res['write']):
        if not res['write'] and readonly:
            res['cause'] = 'nur-lesen'
        elif unmapped(st, unprivileged):
            res['cause'] = 'nobody'
        else:
            res['cause'] = 'rechte'
    if fs_kind == 'nfs':
        res['hints'].append(('NFS: Das NAS entscheidet selbst und kann trotz dieser Rechte ablehnen.',))
        if user['uid'] == 0 and not unprivileged:
            res['hints'].append(('NFS: root wird auf dem NAS meist zu nobody (root_squash).',))
    elif fs_kind == 'smb':
        res['hints'].append(('SMB: Besitzer und Rechte kommen aus den Mount-Optionen (uid=, gid=, file_mode=).',))
    return res
