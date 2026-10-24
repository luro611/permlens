"""UID/GID-Umrechnung zwischen Container und Host.

- Privilegierter Container: Die Nummern sind innen und außen gleich (1:1).
- Unprivilegierter Container ohne eigene Einträge: Proxmox verschiebt alles um 100000
  (Container 0 … 65535 → Host 100000 … 165535).
- Mit `lxc.idmap`: genau die eingetragenen Bereiche. Was in keinem Bereich liegt, ist nicht abgebildet
  und erscheint im Container als nobody (65534)."""

DEFAULT = [{'ct': 0, 'host': 100000, 'count': 65536}]
NOBODY = 65534


def ranges(cfg, kind):
    """Bereiche für 'u' (Benutzer) oder 'g' (Gruppen). None bedeutet 1:1 (privilegiert)."""
    if not cfg.get('unprivileged'):
        return None
    own = [{'ct': r['ct'], 'host': r['host'], 'count': r['count']} for r in cfg.get('idmap', []) if r['kind'] == kind]
    return own or DEFAULT


def to_host(rngs, ct_id):
    """Container-Nummer → Host-Nummer (None = nicht abgebildet)."""
    if rngs is None:
        return ct_id
    for r in rngs:
        if r['ct'] <= ct_id < r['ct'] + r['count']:
            return r['host'] + ct_id - r['ct']
    return None


def to_ct(rngs, host_id):
    """Host-Nummer → Container-Nummer (None = im Container nicht sichtbar, erscheint als nobody)."""
    if rngs is None:
        return host_id
    for r in rngs:
        if r['host'] <= host_id < r['host'] + r['count']:
            return r['ct'] + host_id - r['host']
    return None


def passthrough(rngs):
    """Bereiche, die 1:1 durchgereicht werden (z. B. Container 1000 = Host 1000)."""
    return [r for r in (rngs or []) if r['ct'] == r['host']]


# ---------------------------------------------------------------- Phase 4: Mapping planen
BASE, SIZE = 100000, 65536  # Proxmox-Standard für unprivilegierte Container
PASS_MIN, PASS_MAX = 1, 65533  # 0 (root) und 65534/65535 (nobody) werden nie durchgereicht


def plan_ranges(passthrough, base=BASE, size=SIZE):
    """Lückenlose Bereiche 0 … size-1: die Nummern aus passthrough 1:1, alles andere wie Proxmox um base verschoben.
    Aufeinanderfolgende Nummern werden zu einem Bereich zusammengefasst."""
    ids = sorted(set(passthrough))
    if any(not PASS_MIN <= n <= PASS_MAX for n in ids):
        raise ValueError('Nummer außerhalb von 1 bis 65533')
    out, pos = [], 0
    i = 0
    while i < len(ids):
        start = ids[i]
        end = start
        while i + 1 < len(ids) and ids[i + 1] == end + 1:
            i += 1
            end = ids[i]
        if start > pos:
            out.append({'ct': pos, 'host': base + pos, 'count': start - pos})
        out.append({'ct': start, 'host': start, 'count': end - start + 1})
        pos = end + 1
        i += 1
    if pos < size:
        out.append({'ct': pos, 'host': base + pos, 'count': size - pos})
    return out


def idmap_text(uids, gids):
    """`lxc.idmap`-Zeilen für /etc/pve/lxc/<Nr>.conf (erst Benutzer, dann Gruppen, wie Proxmox sie erwartet)."""
    lines = []
    for kind, ids in (('u', uids), ('g', gids)):
        lines += [f"lxc.idmap: {kind} {r['ct']} {r['host']} {r['count']}" for r in plan_ranges(ids)]
    return lines


def _covered(entries, start, count):
    """Ist start … start+count-1 für root in /etc/subuid bzw. /etc/subgid freigegeben?"""
    return all(any(e['user'] == 'root' and e['start'] <= n < e['start'] + e['count'] for e in entries or [])
               for n in (start, start + count - 1))


def subid_missing(rngs, entries):
    """Zeilen root:Start:Anzahl, die in /etc/subuid bzw. /etc/subgid fehlen, damit diese Bereiche erlaubt sind."""
    missing = [r for r in rngs if not _covered(entries, r['host'], r['count'])]
    out = [f"root:{r['host']}:{r['count']}" for r in missing if r['host'] < BASE]
    if any(r['host'] >= BASE for r in missing):  # verschobene Bereiche: eine Zeile für den Standardbereich reicht
        out.append(f'root:{BASE}:{SIZE}')
    return out


def shared_with(scan, kind, ids, skip=None):
    """Andere Container, die dieselben Host-Nummern durchreichen (oder privilegiert sind und sie so sehen)."""
    hits = []
    for g in (scan or {}).get('guests', []):
        cfg = g.get('config') or {}
        if g['type'] != 'lxc' or not cfg or g['vmid'] == skip:
            continue
        rngs = ranges(cfg, kind)
        for n in ids:
            if (rngs is None and n) or any(r['ct'] <= n < r['ct'] + r['count'] and r['host'] == r['ct'] for r in rngs or []):
                hits.append({'vmid': g['vmid'], 'name': g.get('name', ''), 'id': n, 'privileged': rngs is None})
    return hits
