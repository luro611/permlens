"""Datenbank (SQLite in data/permlens.db).

Tabellen: settings, hosts (verbundene Proxmox, ab 0.5.0), scans (je Host), audit_log und changes
(Änderungen ab Phase 3, mit Gegenbefehl)."""
import contextvars
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    node TEXT NOT NULL DEFAULT '',
    lxc_ip TEXT NOT NULL DEFAULT '',
    guard TEXT NOT NULL DEFAULT '',
    write_ids TEXT NOT NULL DEFAULT '',
    connected INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, started TEXT NOT NULL, finished TEXT, result TEXT, host_id INTEGER);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    result TEXT,
    client TEXT,
    details TEXT
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    client TEXT,
    host TEXT,
    vmid INTEGER,
    ct_name TEXT,
    action TEXT NOT NULL,
    params TEXT,
    shell TEXT,
    rating TEXT,
    result TEXT,
    detail TEXT,
    undo TEXT,
    undo_of INTEGER,
    undone_by INTEGER,
    backup TEXT
);
"""


def connect():
    c = sqlite3.connect(config.DATA / 'permlens.db', timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init():
    with closing(connect()) as c, c:
        c.executescript(SCHEMA)
        cols = {r['name'] for r in c.execute('PRAGMA table_info(changes)')}
        if 'backup' not in cols:  # Datenbank aus 0.2.6 bis 0.2.8
            c.execute('ALTER TABLE changes ADD COLUMN backup TEXT')
        if 'host_id' not in {r['name'] for r in c.execute('PRAGMA table_info(scans)')}:  # bis 0.4.x
            c.execute('ALTER TABLE scans ADD COLUMN host_id INTEGER')
    migrate_host()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def audit(action, target='', result='', client='', **details):
    """Eintrag ins Protokoll. action z. B. 'login', target z. B. ein Container, result 'ok' oder 'fehler'."""
    with closing(connect()) as c, c:
        c.execute('INSERT INTO audit_log (ts, action, target, result, client, details) VALUES (?, ?, ?, ?, ?, ?)',
                  (now(), action, target, result, client, json.dumps(details, ensure_ascii=False) if details else None))


def audit_entries(limit=200):
    with closing(connect()) as c:
        return [dict(r) for r in c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,))]


def get_setting(key, default=''):
    with closing(connect()) as c:
        row = c.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def set_settings(**values):
    with closing(connect()) as c, c:
        c.executemany('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                      list(values.items()))


# ---------------------------------------------------------------- Mehrere Proxmox (ab 0.5.0)
HOST_FIELDS = ('name', 'host', 'port', 'node', 'lxc_ip', 'guard', 'write_ids', 'connected')
# Aktiver Host der laufenden Anfrage (aus dem Cookie, gesetzt in main.py). None = der erste Host.
ACTIVE = contextvars.ContextVar('permlens_host', default=None)


def migrate_host():
    """Bis 0.4.x gab es genau eine Verbindung in settings. Sie wird einmal als erster Host übernommen,
    samt der bisher eingelesenen Stände. Danach stehen in settings keine Verbindungsdaten mehr."""
    host = get_setting('pve_host')
    if not host:
        return None
    with closing(connect()) as c, c:
        if c.execute('SELECT 1 FROM hosts LIMIT 1').fetchone():
            return None
        port = get_setting('pve_port', '22')
        hid = c.execute('INSERT INTO hosts (name, host, port, node, lxc_ip, guard, write_ids, connected, created) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (get_setting('pve_node') or host, host, int(port) if port.isdigit() else 22,
                         get_setting('pve_node'), get_setting('lxc_ip'), get_setting('pve_guard'),
                         get_setting('pve_write'), 1 if get_setting('pve_connected') == '1' else 0, now())).lastrowid
        c.execute('UPDATE scans SET host_id = ? WHERE host_id IS NULL', (hid,))
        c.execute("DELETE FROM settings WHERE key IN ('pve_host', 'pve_port', 'pve_node', 'pve_guard', 'pve_write', "
                  "'pve_connected')")
    return hid


def hosts():
    with closing(connect()) as c:
        return [dict(r) for r in c.execute('SELECT * FROM hosts ORDER BY id')]


def host(hid):
    with closing(connect()) as c:
        r = c.execute('SELECT * FROM hosts WHERE id = ?', (hid,)).fetchone()
    return dict(r) if r else None


def active_host():
    """Host dieser Anfrage: der im Cookie gewählte, sonst der erste. None, wenn noch keiner eingerichtet ist."""
    hid = ACTIVE.get()
    return (host(hid) if hid else None) or next(iter(hosts()), None)


def find_host(address, port=22):
    with closing(connect()) as c:
        r = c.execute('SELECT * FROM hosts WHERE host = ? AND port = ?', (address, int(port))).fetchone()
    return dict(r) if r else None


def add_host(address, port=22, **fields):
    """Neuen Host anlegen oder, wenn es Adresse und Port schon gibt, diesen aktualisieren. Gibt die id zurück."""
    old = find_host(address, port)
    if old:
        update_host(old['id'], **fields)
        return old['id']
    fields.setdefault('name', fields.get('node') or address)
    keys = [k for k in HOST_FIELDS if k in fields and k not in ('host', 'port')]
    with closing(connect()) as c, c:
        return c.execute(f'INSERT INTO hosts (host, port, created{"".join(", " + k for k in keys)}) '
                         f'VALUES (?, ?, ?{", ?" * len(keys)})',
                         (address, int(port), now(), *(fields[k] for k in keys))).lastrowid


def update_host(hid, **fields):
    keys = [k for k in HOST_FIELDS if k in fields]
    if not keys:
        return
    with closing(connect()) as c, c:
        c.execute(f'UPDATE hosts SET {", ".join(k + " = ?" for k in keys)} WHERE id = ?',
                  (*(fields[k] for k in keys), hid))


def delete_host(hid):
    """Host aus PermLens entfernen, mit seinen eingelesenen Ständen. Das Protokoll der Änderungen bleibt."""
    with closing(connect()) as c, c:
        c.execute('DELETE FROM scans WHERE host_id = ?', (hid,))
        c.execute('DELETE FROM hosts WHERE id = ?', (hid,))
