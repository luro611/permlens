"""Kompletter Scan: Inventar aller Gäste und die Einstellungen jedes LXC. Das Ergebnis wird gespeichert."""
import json
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from .. import db
from . import docker, parse, ssh

WORKERS = 6
KEEP = 30
_lock = threading.Lock()


def _lxc(host, port, guest):
    r = ssh.run(host, ['pct', 'config', str(guest['vmid'])], port, timeout=30)
    if not r.ok:
        return {**guest, 'error': ssh.explain(r)}
    return {**guest, 'config': parse.pct_config(r.out), 'error': ''}


HOST_CMDS = {
    'passwd': ['getent', 'passwd'],
    'group': ['getent', 'group'],
    'mounts': ['findmnt', '-J', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'],
    'subuid': ['cat', '/etc/subuid'],
    'subgid': ['cat', '/etc/subgid'],
    'storage': ['cat', '/etc/pve/storage.cfg'],
}
PARSERS = {'passwd': parse.passwd, 'group': parse.group, 'mounts': parse.findmnt,
           'subuid': parse.subid, 'subgid': parse.subid, 'storage': parse.storage_cfg}
STAT = ['stat', '-c', '%A|%a|%u|%g|%U|%G|%F|%n']
FINDMNT = HOST_CMDS['mounts']
STAT_TIMEOUT = 10  # je Ordner; eine ausgeschaltete NAS soll den Scan nicht aufhalten


def _stat_one(host, port, path, vmid=None):
    """Einen Ordner abfragen (auf dem Host oder im Container). Gibt (stat oder None, keine_antwort) zurück."""
    cmd = (['pct', 'exec', str(vmid), '--'] if vmid else []) + STAT + [path]
    r = ssh.run(host, cmd, port, timeout=STAT_TIMEOUT)
    return parse.stat(r.out).get(path), r.rc == 124


def _host_info(host, port, pool):
    """Benutzer, Gruppen, Mounts und subuid/subgid des Hosts."""
    def one(item):
        name, cmd = item
        r = ssh.run(host, cmd, port, timeout=30)
        try:
            return name, PARSERS[name](r.out) if r.ok else []
        except ValueError:
            return name, []
    return dict(pool.map(one, HOST_CMDS.items()))


def _details(host, port, guest, skip=(), guard=2):
    """Benutzer, Gruppen und Rechte der Mount-Ziele aus Sicht des laufenden Containers."""
    vmid = str(guest['vmid'])
    d = {'users': [], 'groups': [], 'stat': {}, 'errors': []}
    for key, cmd, fn in (('users', ['getent', 'passwd'], parse.passwd), ('groups', ['getent', 'group'], parse.group)):
        r = ssh.run(host, ['pct', 'exec', vmid, '--'] + cmd, port, timeout=30)
        if r.ok:
            d[key] = fn(r.out)
        else:
            d['errors'].append(ssh.explain(r))
    d['offline'] = []
    for m in guest['config']['mounts']:  # einzeln, damit ein hängender Ordner die anderen nicht blockiert
        if not m['target']:
            continue
        if m['source'] in skip:  # Quelle antwortet schon auf dem Host nicht: nicht noch einmal abwarten
            d['offline'].append(m['target'])
            continue
        st, timeout = _stat_one(host, port, m['target'], vmid)
        if st:
            d['stat'][m['target']] = st
        elif timeout:
            d['offline'].append(m['target'])
    # Eigene NFS/SMB-Mounts des Containers (Weg E) und Samba-Freigaben (Weg G)
    r = ssh.run(host, ['pct', 'exec', vmid, '--'] + FINDMNT, port, timeout=30)
    try:
        passed = {m['target'] for m in guest['config']['mounts']}  # vom Host durchgereichte zählen nicht
        d['own_mounts'] = [x for x in parse.findmnt(r.out)
                           if kind_of(x) in ('nfs', 'smb') and x['target'] not in passed] if r.ok else []
    except ValueError:
        d['own_mounts'] = []
    r = ssh.run(host, ['pct', 'exec', vmid, '--', 'testparm', '-s'], port, timeout=30)
    smb = parse.testparm(r.out) if r.ok else {'shares': []}
    d['samba'] = smb if smb['shares'] else None
    d['exports'] = []
    if guard >= 3:  # NFS-Server im Container (Weg H)
        r = ssh.run(host, ['pct', 'exec', vmid, '--', 'cat', '/etc/exports'], port, timeout=20)
        d['exports'] = parse.exports(r.out) if r.ok else []
    # Ordner auf dem Weg zu den Mount-Zielen (für den Rechte-Rechner), alle in einem Aufruf
    targets = {m['target'] for m in guest['config']['mounts'] if m['target']}
    up = sorted({q for t in targets for q in parents(t)} - targets)
    if up:
        r = ssh.run(host, ['pct', 'exec', vmid, '--'] + STAT + up, port, timeout=STAT_TIMEOUT)
        d['stat'].update(parse.stat(r.out))  # fehlt ein Ordner, kommen die anderen trotzdem
    if guard >= 8:  # Docker-Apps im LXC (AP 6.2), nur lesend
        dk = docker.collect(host, port, vmid, STAT, STAT_TIMEOUT)
        if dk is not None:
            d['stat'].update(dk.pop('stat', {}) or {})
            d['docker'] = dk
    return d


PATH_OK = re.compile(r'^/[A-Za-z0-9 ._@+,:=~/-]*$')  # wie im Wächter-Script


def valid_path(path):
    p = path or ''
    return bool(PATH_OK.match(p)) and '/../' not in p + '/' and '/./' not in p + '/' and len(p) < 1024


def stat_live(host, port, vmid, path):
    """Einen Pfad und alle Ordner davor jetzt im Container abfragen (für die Diagnose eigener Pfade)."""
    r = ssh.run(host, ['pct', 'exec', str(vmid), '--'] + STAT + parents(path) + [path], port, timeout=STAT_TIMEOUT)
    return parse.stat(r.out), r


def probe(host, port, vmid, uid, gid, gids, path):
    """Gegenprobe (Wächter 3): fragt das System im Container als dieser Benutzer, ohne etwas zu schreiben.
    Gibt {r, w, x: True/False/None, error} zurück. None = keine Antwort."""
    groups = '--groups=' + ','.join(str(x) for x in sorted({gid, *gids})) if gids else '--clear-groups'
    out = {'error': ''}
    for flag in ('r', 'w', 'x'):
        r = ssh.run(host, ['pct', 'exec', str(vmid), '--', 'setpriv', f'--reuid={uid}', f'--regid={gid}', groups,
                           '--', 'test', '-' + flag, path], port, timeout=STAT_TIMEOUT)
        if r.rc in (0, 1):
            out[flag] = r.rc == 0
            continue
        out[flag] = None
        out['error'] = ('Keine Antwort. Ist das NAS ausgeschaltet?' if r.rc == 124 else
                        'Der Wächter auf dem Proxmox kennt die Gegenprobe noch nicht. Bitte „Neu einrichten“.' if r.rc == ssh.DENIED else
                        'Im Container fehlt setpriv (z. B. bei Alpine). Die Gegenprobe geht dort nicht.' if r.rc == 127 or 'setpriv' in r.err else
                        ssh.explain(r))
        break
    return out


def parents(path):
    """'/mnt/a/b' → ['/', '/mnt', '/mnt/a']"""
    parts = [x for x in path.split('/') if x]
    return ['/'] + ['/' + '/'.join(parts[:i]) for i in range(1, len(parts))]


def fs_for(path, host_mounts):
    """Dateisystem des Hosts, auf dem ein Pfad liegt (längster passender Mount)."""
    best = None
    for m in host_mounts:
        t = m['target'].rstrip('/') or '/'
        if (path == t or path.startswith(t + '/') or t == '/') and (best is None or len(t) > len(best['target'])):
            best = m
    return best


def kind_of(fs):
    t = (fs or {}).get('fstype', '')
    if t.startswith('nfs'):
        return 'nfs'
    if t in ('cifs', 'smb3'):
        return 'smb'
    return 'lokal'


def _mount_info(host, port, guests, host_mounts, pool, guard=2):
    """Rechte und ACLs aller Bind-Mount-Quellen auf dem Host, an jeden Mount angehängt."""
    sources = sorted({m['source'] for g in guests for m in (g.get('config') or {}).get('mounts', [])
                      if m['kind'] == 'bind' and (guard >= 3 or not m.get('entry'))})  # lxc.mount.entry ab Wächter 3
    results = dict(zip(sources, pool.map(lambda s: _stat_one(host, port, s), sources)))
    stats = {s: st for s, (st, _) in results.items() if st}
    offline = {s for s, (st, timeout) in results.items() if not st and timeout}

    def acl(path):
        r = ssh.run(host, ['acl', path], port, timeout=20)
        try:
            return path, json.loads(r.out) if r.ok else None
        except ValueError:
            return path, None
    acls = dict(pool.map(acl, [s for s in sources if s in stats]))
    for g in guests:
        for m in (g.get('config') or {}).get('mounts', []):
            if m['kind'] != 'bind':
                continue
            fs = fs_for(m['source'], host_mounts)
            if m.get('entry') and guard < 3:  # Host-Rechte unbekannt, Art des Speichers aber schon
                m.update(host_stat=None, acl=None, fs=fs, fs_kind=kind_of(fs), host_unchecked=True)
                continue
            m['host_stat'] = stats.get(m['source'])
            m['acl'] = acls.get(m['source'])
            m['fs'] = fs
            m['fs_kind'] = kind_of(fs) if m['host_stat'] else ('offline' if m['source'] in offline else 'fehlt')
    return offline


def run(host, port=22, host_id=None):
    """Scan ausführen und speichern. Gibt das Ergebnis zurück (auch bei Fehlern, dann mit 'error').
    host_id: Eintrag in der Tabelle hosts, zu dem der Stand gehört (ab 0.5.0)."""
    with _lock:  # nie zwei Scans gleichzeitig
        result = {'started': db.now(), 'finished': '', 'host': host, 'host_id': host_id, 'guests': [], 'error': ''}
        try:
            info = ssh.guard_info(host, port)[0]
            guard = info.get('guard')
            if guard and host_id:  # für die Einstellungsseite merken, ebenso die zum Schreiben freigegebenen Container
                db.update_host(host_id, guard=str(guard), write_ids=str(info.get('write_ids') or ''))
            gv = int(guard) if str(guard or '').isdigit() else 2
            result['guard'] = gv
            # ab Wächter 9: Container und Ordner, für die Ändern am Host freigegeben ist (/etc/permlens/host-aendern-erlaubt)
            result['host_change'] = {'ids': str(info.get('host_ids') or ''),
                                     'paths': [p for p in info.get('host_paths') or [] if isinstance(p, str)]}
            r = ssh.run(host, ['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], port)
            if r.ok:
                try:
                    guests = parse.resources(r.out)
                except ValueError:
                    guests, result['error'] = [], 'Die Antwort des Proxmox war nicht lesbar.'
                lxcs = [g for g in guests if g['type'] == 'lxc']
                with ThreadPoolExecutor(WORKERS) as pool:
                    done = {g['vmid']: g for g in pool.map(lambda g: _lxc(host, port, g), lxcs)}
                    result['guests'] = [done.get(g['vmid'], g) for g in guests]
                    result['host_info'] = _host_info(host, port, pool)
                    offline = _mount_info(host, port, result['guests'], result['host_info'].get('mounts', []), pool, gv)
                    running = [g for g in result['guests'] if g.get('config') and g['status'] == 'running']
                    for g, d in zip(running, pool.map(lambda g: _details(host, port, g, offline, gv), running)):
                        g['details'] = d
            else:
                result['error'] = ssh.explain(r)
        except Exception as e:  # ohne das bliebe nur der alte Stand stehen, ohne Hinweis
            traceback.print_exc()
            result.update(guests=[], error=f'Interner Fehler beim Einlesen ({type(e).__name__}: {e}). Details im Protokoll des Containers.')
        result['finished'] = db.now()
        save(result)
        return result


_state = {'running': False, 'started': '', 'failed': ''}


def running(host_id=None):
    """Läuft gerade ein Scan? Mit host_id: einer für genau diesen Host."""
    return _state['running'] and (host_id is None or _state.get('host_id') == host_id)


def failed_since(finished):
    """True, wenn nach dem gespeicherten Stand ein Einlesen gescheitert ist, das nichts speichern konnte."""
    return bool(_state['failed']) and _state['failed'] >= (finished or '')


def start(host, port=22, on_done=None, host_id=None):
    """Scan im Hintergrund starten (falls nicht schon einer läuft). on_done(result) wird danach aufgerufen."""
    if _state['running']:
        return False
    _state.update(running=True, started=db.now(), failed='', host_id=host_id)

    def work():
        try:
            result = run(host, port, host_id)
            if on_done:
                on_done(result)
        except Exception:  # z. B. Datenbank nicht beschreibbar: wenigstens im Protokoll des Containers sichtbar
            traceback.print_exc()
            _state['failed'] = db.now()
        finally:
            _state['running'] = False
    threading.Thread(target=work, daemon=True, name='scan').start()
    return True


def save(result):
    hid = result.get('host_id') or (db.active_host() or {}).get('id')
    with closing(db.connect()) as c, c:
        c.execute('INSERT INTO scans (started, finished, result, host_id) VALUES (?, ?, ?, ?)',
                  (result['started'], result['finished'], json.dumps(result, ensure_ascii=False), hid))
        c.execute('DELETE FROM scans WHERE host_id IS ? AND id NOT IN '
                  '(SELECT id FROM scans WHERE host_id IS ? ORDER BY id DESC LIMIT ?)', (hid, hid, KEEP))


def latest(host_id=None):
    """Letzter gespeicherter Scan des Hosts (ohne Angabe: des aktiven Hosts dieser Anfrage) oder None."""
    if host_id is None:
        h = db.active_host()
        if not h:
            return None
        host_id = h['id']
    with closing(db.connect()) as c:
        row = c.execute('SELECT result FROM scans WHERE host_id = ? ORDER BY id DESC LIMIT 1', (host_id,)).fetchone()
    return json.loads(row['result']) if row else None


def status(guest):
    """Einfache Ampel für Phase 1: ok (läuft, lesbar), aus (gestoppt), fehler (nicht lesbar)."""
    if guest.get('error'):
        return 'fehler'
    return 'ok' if guest.get('status') == 'running' else 'aus'


def mapping(cfg):
    """'privilegiert', 'standard' (unprivilegiert, Standard-Mapping) oder 'eigen' (lxc.idmap)."""
    if not cfg.get('unprivileged'):
        return 'privilegiert'
    return 'eigen' if cfg.get('idmap') else 'standard'
