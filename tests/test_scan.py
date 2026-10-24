"""Inventar und Container-Einstellungen auslesen (mit anonymisierten Beispieldaten, ohne echten Proxmox)."""
from pathlib import Path

from app import db
from app.pve import parse, scan, ssh
from app.pve.scan import start as REAL_START  # vor der Test-Abkürzung aus conftest geladen
from conftest import get_pve, set_pve  # noqa: E402

FIX = Path(__file__).parent / 'fixtures'


def fixture(name):
    return (FIX / name).read_text()


def test_resources():
    g = parse.resources(fixture('resources.json'))
    assert [x['vmid'] for x in g] == [106, 112, 113, 9005]  # sortiert, ohne Vorlage und Speicher
    assert g[1]['tags'] == ['debian13', 'samba']
    assert g[0]['type'] == 'qemu'


def test_config_privilegiert_mit_mounts():
    c = parse.pct_config(fixture('pct_config_112.txt'))
    assert c['hostname'] == 'samba'
    assert c['unprivileged'] is False  # keine Zeile „unprivileged“ = privilegiert
    assert c['features'] == {'mount': 'nfs;cifs', 'nesting': '1'}
    assert c['ip'] == '10.0.0.12/24'
    assert c['onboot'] is True
    assert [(m['source'], m['target'], m['readonly']) for m in c['mounts']] == [
        ('/mnt/daten', '/mnt/daten', False), ('/mnt/teilen', '/mnt/teilen', True)]
    assert all(m['key'] != 'mp9' for m in c['mounts'])  # Snapshot-Abschnitt ignoriert
    assert scan.mapping(c) == 'privilegiert'


def test_config_unprivilegiert_mit_idmap():
    c = parse.pct_config(fixture('pct_config_9005.txt'))
    assert c['unprivileged'] is True
    assert [m['key'] for m in c['mounts']] == ['mp0', 'mp1']
    assert c['mounts'][0]['kind'] == 'volume' and c['mounts'][1]['kind'] == 'bind'
    assert {'kind': 'u', 'ct': 1000, 'host': 1000, 'count': 1} in c['idmap']
    assert len(c['idmap']) == 6
    assert scan.mapping(c) == 'eigen'


def test_config_unprivilegiert_standard():
    assert scan.mapping(parse.pct_config('unprivileged: 1\n')) == 'standard'


def fake_run(answers):
    def run(host, args, port=22, timeout=75):
        key = ' '.join(args)
        if key in answers:
            return answers[key]
        return ssh.Result(255, '', 'root@x: Permission denied (publickey).')
    return run


def test_scan_und_speichern(monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_run({
        'pvesh get /cluster/resources --type vm --output-format json': ssh.Result(0, fixture('resources.json'), ''),
        'pct config 112': ssh.Result(0, fixture('pct_config_112.txt'), ''),
        'pct config 113': ssh.Result(0, 'unprivileged: 1\n', ''),
    }))
    r = scan.run('10.0.0.5')
    assert r['error'] == ''
    by_id = {g['vmid']: g for g in r['guests']}
    assert scan.status(by_id[112]) == 'ok'
    assert scan.status(by_id[113]) == 'aus'
    assert scan.status(by_id[9005]) == 'fehler'  # pct config ging schief
    assert 'config' not in by_id[106]  # VMs werden nicht weiter befragt
    assert scan.latest()['guests'] == r['guests']


def test_scan_ohne_verbindung(monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_run({}))
    r = scan.run('10.0.0.5')
    assert 'kennt den Schlüssel' in r['error']
    assert r['guests'] == []


def test_scan_mit_internem_fehler_wird_gespeichert(monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_run({
        'pvesh get /cluster/resources --type vm --output-format json': ssh.Result(0, fixture('resources.json'), ''),
    }))
    monkeypatch.setattr(scan, '_host_info', lambda *a: 1 / 0)
    r = scan.run('10.0.0.5')
    assert 'ZeroDivisionError' in r['error']
    assert r['guests'] == []
    assert scan.latest()['error'] == r['error']  # neuer Stand statt still der alte


def test_speicherfehler_wird_auf_der_startseite_gemeldet(client, monkeypatch):
    import time
    set_pve(pve_host='10.0.0.5', pve_port='22', pve_connected='1')
    monkeypatch.setattr(scan, 'run', lambda h, p, i=None: 1 / 0)  # z. B. Datenbank nicht beschreibbar
    assert REAL_START('10.0.0.5')
    for _ in range(200):
        if not scan.running():
            break
        time.sleep(0.01)
    assert 'konnte nicht gespeichert werden' in client.get('/').text
    monkeypatch.setattr(scan, 'run', lambda h, p, i=None: scan.save({'started': '', 'finished': db.now(), 'host': h, 'guests': [], 'error': ''}))
    assert REAL_START('10.0.0.5')  # ein gelungener Versuch nimmt den Hinweis weg
    for _ in range(200):
        if not scan.running():
            break
        time.sleep(0.01)
    assert 'konnte nicht gespeichert werden' not in client.get('/').text


def test_uebersicht(client, monkeypatch):
    set_pve(pve_host='10.0.0.5', pve_port='22')
    monkeypatch.setattr(ssh, 'run', fake_run({
        'pvesh get /cluster/resources --type vm --output-format json': ssh.Result(0, fixture('resources.json'), ''),
        'pct config 112': ssh.Result(0, fixture('pct_config_112.txt'), ''),
        'pct config 113': ssh.Result(0, 'unprivileged: 1\n', ''),
        'pct config 9005': ssh.Result(0, fixture('pct_config_9005.txt'), ''),
    }))
    r = client.post('/scan')
    assert r.status_code == 200
    for text in ('samba', 'mit-idmap', 'backup-vm', 'privilegiert', 'eigenes', 'Virtuelle Maschinen', 'Neu einlesen'):
        assert text in r.text, text
    assert db.audit_entries(1)[0]['action'] == 'scan'


def test_alte_scans_werden_geloescht(monkeypatch):
    set_pve(pve_host='10.0.0.5')
    monkeypatch.setattr(scan, 'KEEP', 3)
    for i in range(5):
        scan.save({'started': str(i), 'finished': str(i), 'host': 'x', 'guests': [], 'error': ''})
    from contextlib import closing
    with closing(db.connect()) as c:
        hid = db.active_host()['id']  # aufgehoben werden KEEP Stände je Proxmox
        assert c.execute('SELECT COUNT(*) FROM scans WHERE host_id = ?', (hid,)).fetchone()[0] == 3
    assert scan.latest()['started'] == '4'


def test_ausgeschaltete_nas_haelt_nichts_auf(monkeypatch):
    """Ein Ordner, der nicht antwortet (Zeitlimit), wird als offline markiert; die anderen werden normal gelesen."""
    cfg = 'hostname: x\nunprivileged: 1\nmp0: /mnt/lokal,mp=/a\nmp1: /mnt/nas,mp=/b\n'
    res = '[{"type": "lxc", "vmid": 300, "name": "x", "status": "running"}]'

    def run(host, args, port=22, timeout=75):
        cmd = ' '.join(args)
        if cmd.startswith('pvesh'):
            return ssh.Result(0, res, '')
        if cmd == 'pct config 300':
            return ssh.Result(0, cfg, '')
        if args[0] == 'stat' or (args[:2] == ['pct', 'exec'] and 'stat' in args):
            path = args[-1]
            if path in ('/mnt/nas', '/b'):
                return ssh.Result(124, '', 'Zeitlimit')
            return ssh.Result(0, f'drwxr-xr-x|755|0|0|root|root|directory|{path}', '')
        if args[0] == 'acl':
            return ssh.Result(0, '{"path": "x", "access": [], "default": []}', '')
        return ssh.Result(0, '', '')
    monkeypatch.setattr(ssh, 'run', run)
    r = scan.run('10.0.0.5')
    mounts = {m['source']: m for m in r['guests'][0]['config']['mounts']}
    assert mounts['/mnt/lokal']['fs_kind'] == 'lokal' and mounts['/mnt/lokal']['host_stat']['uid'] == 0
    assert mounts['/mnt/nas']['fs_kind'] == 'offline'
    d = r['guests'][0]['details']
    assert '/a' in d['stat'] and d['offline'] == ['/b']


def test_scan_im_hintergrund(monkeypatch):
    """Der echte Start läuft im Hintergrund; ein zweiter Start während des ersten wird ignoriert."""
    import threading
    gate, done = threading.Event(), threading.Event()
    monkeypatch.setattr(scan, 'run', lambda h, p=22, i=None: gate.wait(5) and {'error': '', 'guests': []})
    assert REAL_START('10.0.0.5', on_done=lambda r: done.set()) is True
    assert scan.running() is True
    assert REAL_START('10.0.0.5') is False
    gate.set()
    assert done.wait(5)
    for _ in range(50):
        if not scan.running():
            break
        threading.Event().wait(0.05)
    assert scan.running() is False


def test_scan_merkt_waechter_version(monkeypatch):
    from app import db
    set_pve(pve_host='10.0.0.5', pve_guard='')
    monkeypatch.setattr(ssh, 'run', fake_run({'version': ssh.Result(0, '{"guard": "2"}', '')}))
    scan.run('10.0.0.5', 22, db.active_host()['id'])
    assert get_pve('pve_guard') == '2'
