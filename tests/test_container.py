"""Benutzer, Mapping und Mounts je Container (mit Beispieldaten)."""
import json
from pathlib import Path

from app import db
from app.pve import mapping as M
from app.pve import parse, scan, ssh, view
from conftest import set_pve  # noqa: E402

FIX = Path(__file__).parent / 'fixtures'

PASSWD = 'root:x:0:0:root:/root:/bin/bash\nwww-data:x:33:33:www-data:/var/www:/usr/sbin/nologin\n' \
         'alice:x:1000:1000:,,,:/home/alice:/bin/bash\nbob:x:1001:1001::/home/bob:/bin/sh\n' \
         'nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n'
GROUP = 'root:x:0:\nalice:x:1000:\nbob:x:1001:\nmedia:x:2000:alice,bob\n'
HOST_PASSWD = 'root:x:0:0:root:/root:/bin/bash\npaperless:x:1000:1000::/home/paperless:/usr/sbin/nologin\n'
HOST_GROUP = 'root:x:0:\nsmbusers:x:1000:luro\n'


# ---------------------------------------------------------------- Umrechnung
def test_privilegiert_ist_eins_zu_eins():
    r = M.ranges({'unprivileged': False}, 'u')
    assert r is None and M.to_host(r, 1000) == 1000 and M.to_ct(r, 0) == 0


def test_standard_mapping():
    r = M.ranges({'unprivileged': True, 'idmap': []}, 'u')
    assert M.to_host(r, 0) == 100000
    assert M.to_host(r, 1000) == 101000
    assert M.to_host(r, 65536) is None
    assert M.to_ct(r, 1000) is None  # Host-UID 1000 ist im Container nicht sichtbar → nobody
    assert M.to_ct(r, 101000) == 1000


def test_eigenes_mapping():
    cfg = parse.pct_config((FIX / 'pct_config_9005.txt').read_text())
    u = M.ranges(cfg, 'u')
    assert M.to_host(u, 999) == 100999
    assert M.to_host(u, 1000) == 1000
    assert M.to_host(u, 1001) == 101001
    assert M.to_ct(u, 1000) == 1000
    assert M.passthrough(u) == [{'ct': 1000, 'host': 1000, 'count': 1}]
    assert M.ranges(cfg, 'g') is not None


# ---------------------------------------------------------------- Auslesen
def test_passwd_und_group():
    users = parse.passwd(PASSWD)
    assert [u['name'] for u in users] == ['root', 'www-data', 'alice', 'bob', 'nobody']
    assert users[2]['home'] == '/home/alice'
    groups = parse.group(GROUP)
    assert groups[3] == {'name': 'media', 'gid': 2000, 'members': ['alice', 'bob']}


def test_stat():
    s = parse.stat('drwxrwsr-x|2775|1000|1000|paperless|smbusers|directory|/mnt/daten\n'
                   'drwx------|700|0|0|root|root|directory|/mit|senkrechtem strich\n')
    assert s['/mnt/daten']['uid'] == 1000 and s['/mnt/daten']['mode'] == 'drwxrwsr-x'
    assert '/mit|senkrechtem strich' in s


def test_findmnt_und_dateisystem():
    mounts = parse.findmnt((FIX / 'findmnt.json').read_text())
    assert len(mounts) == 4
    assert scan.kind_of(scan.fs_for('/mnt/nas/unterordner', mounts)) == 'nfs'
    assert scan.kind_of(scan.fs_for('/mnt/smb', mounts)) == 'smb'
    assert scan.fs_for('/mnt/daten', mounts)['source'] == '/dev/sdb1'
    assert scan.fs_for('/mnt/datenbank', mounts)['target'] == '/'  # nur ganze Pfadteile zählen
    assert scan.kind_of(scan.fs_for('/srv', mounts)) == 'lokal'


def test_subid():
    assert parse.subid('root:100000:65536\nroot:1000:1\nkaputt\n') == [
        {'user': 'root', 'start': 100000, 'count': 65536}, {'user': 'root', 'start': 1000, 'count': 1}]


# ---------------------------------------------------------------- kompletter Scan mit Details
def fake_proxmox(host, args, port=22, timeout=75):
    cmd = ' '.join(args)
    out = {
        'pvesh get /cluster/resources --type vm --output-format json': (FIX / 'resources.json').read_text(),
        'pct config 112': (FIX / 'pct_config_112.txt').read_text(),
        'pct config 113': 'hostname: gestoppt\nunprivileged: 1\nmp0: /gibt/es/nicht,mp=/daten\n',
        'pct config 9005': (FIX / 'pct_config_9005.txt').read_text(),
        'getent passwd': HOST_PASSWD, 'getent group': HOST_GROUP,
        'findmnt -J -o TARGET,SOURCE,FSTYPE,OPTIONS': (FIX / 'findmnt.json').read_text(),
        'cat /etc/subuid': 'root:100000:65536\nroot:1000:1\n', 'cat /etc/subgid': 'root:100000:65536\nroot:1000:1\n',
    }
    if cmd in out:
        return ssh.Result(0, out[cmd], '')
    if args[:2] == ['pct', 'exec'] and args[4:] == ['getent', 'passwd']:
        return ssh.Result(0, PASSWD, '')
    if args[:2] == ['pct', 'exec'] and args[4:] == ['getent', 'group']:
        return ssh.Result(0, GROUP, '')
    if args[:2] == ['pct', 'exec'] and args[4] == 'stat':
        lines = [f'drwxrwsr-x|2775|1000|1000|alice|alice|directory|{p}' for p in args[7:]]
        return ssh.Result(0, '\n'.join(lines), '')
    if args[0] == 'stat':
        known = {'/mnt/daten': '1000|1000|paperless|smbusers', '/mnt/teilen': '0|0|root|root',
                 '/srv/test/share': '1000|1000|paperless|smbusers'}
        lines = [f'drwxrwsr-x|2775|{known[p]}|directory|{p}' for p in args[3:] if p in known]
        return ssh.Result(1 if len(lines) < len(args) - 3 else 0, '\n'.join(lines), 'stat: cannot statx')
    if args[0] == 'acl':
        acl = {'path': args[1], 'access': [], 'default': []}
        if args[1] == '/mnt/daten':
            acl['access'] = [{'tag': 'user_obj', 'id': None, 'perm': 'rwx'}, {'tag': 'user', 'id': 1000, 'perm': 'r-x'}]
        return ssh.Result(0, json.dumps(acl), '')
    return ssh.Result(126, '', 'permlens-guard: Befehl nicht erlaubt')


def test_scan_mit_details(monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_proxmox)
    r = scan.run('10.0.0.5')
    assert r['error'] == ''
    assert r['host_info']['passwd'][1]['name'] == 'paperless'
    g = view.find(r, 112)
    assert g['details']['users'][2]['name'] == 'alice'
    daten = g['config']['mounts'][0]
    assert daten['host_stat']['uid'] == 1000 and daten['fs_kind'] == 'lokal' and daten['fs']['source'] == '/dev/sdb1'
    assert daten['acl']['access'][1]['id'] == 1000
    gestoppt = view.find(r, 113)
    assert 'details' not in gestoppt
    assert gestoppt['config']['mounts'][0]['fs_kind'] == 'fehlt'


def test_ansicht_standard_und_eigenes_mapping(monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_proxmox)
    r = scan.run('10.0.0.5')
    v = view.container(r, view.find(r, 9005))
    alice = next(u for u in v['users'] if u['name'] == 'alice')
    assert alice['host_uid'] == 1000 and alice['host_user'] == 'paperless'
    assert alice['groups'] == ['media']
    bob = next(u for u in v['users'] if u['name'] == 'bob')
    assert bob['host_uid'] == 101001 and bob['host_user'] == ''
    assert next(u for u in v['users'] if u['name'] == 'www-data')['system'] is True
    assert next(u for u in v['users'] if u['name'] == 'root')['system'] is False
    assert [x['same'] for x in v['urows']] == [False, True, False]
    assert v['urows'][1]['name'] == 'paperless'

    v112 = view.container(r, view.find(r, 112))
    assert v112['urows'] is None  # privilegiert: 1:1
    daten = v112['mounts'][0]
    assert daten['acl_entries'][0]['name'] == 'paperless'

    v113 = view.container(r, view.find(r, 113))
    assert v113['running'] is False and v113['mounts'][0]['fs_kind'] == 'fehlt'


def test_erwarteter_besitzer_bei_gestopptem_container():
    cfg = {'unprivileged': True, 'idmap': [], 'mounts': [
        {'key': 'mp0', 'source': '/mnt/daten', 'target': '/daten', 'kind': 'bind', 'readonly': False, 'options': {},
         'host_stat': {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 1000, 'gid': 1000, 'user': '', 'group': '',
                       'type': 'directory'}, 'acl': None, 'fs': None, 'fs_kind': 'lokal'}]}
    v = view.container({'guests': []}, {'vmid': 200, 'type': 'lxc', 'name': 'x', 'status': 'stopped', 'config': cfg})
    assert v['mounts'][0]['expected'] == {'uid': 65534, 'gid': 65534, 'unmapped': True}


def test_container_seite(client, monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_proxmox)
    set_pve(pve_host='10.0.0.5', pve_port='22')
    client.post('/scan')
    r = client.get('/container/9005?tab=benutzer')
    assert r.status_code == 200 and 'paperless' in r.text and 'Systembenutzer anzeigen' in r.text
    r = client.get('/container/9005')  # Überblick mit Mapping
    assert 'durchgereicht' in r.text and '100999' in r.text and 'mapping?art=bestehend&amp;ct=9005' in r.text
    r = client.get('/container/112?tab=mapping')  # alte Adresse
    assert 'privilegierter Container' in r.text and 'mapping?art=umstieg&amp;ct=112' in r.text
    assert 'Unprivilegiert machen …' in r.text
    r = client.get('/container/112?tab=mounts')
    assert '/mnt/daten' in r.text and 'Zusätzliche Rechte (ACL)' in r.text
    r = client.get('/container/113?tab=mounts')
    assert 'gibt es auf dem Host nicht' in r.text and 'gestoppt' in r.text
    assert client.get('/container/106', follow_redirects=False).status_code == 303  # VM: keine Detailseite
    assert client.get('/container/4242', follow_redirects=False).status_code == 303



# ---------------------------------------------------------------- Host-Einstellungen (0.5.6)
def test_conf_zeilen_notiz_und_snapshots():
    cfg = parse.pct_config('description: Mein%20NAS%0Azweite%20Zeile\n' + (FIX / 'pct_config_112.txt').read_text())
    assert cfg['lines'][0] == ['arch', 'amd64'] and ['mp1', '/mnt/teilen,mp=/mnt/teilen,ro=1'] in cfg['lines']
    assert not any(k == 'mp9' for k, _ in cfg['lines'])  # Zeile aus dem Snapshot
    assert cfg['snapshots'] == ['vor-update']
    assert cfg['description'] == 'Mein NAS\nzweite Zeile' and 'description' not in cfg['raw']

    from app.pve import explain
    rows = {r['key']: r for r in explain.conf(parse.pct_config((FIX / 'pct_config_9005.txt').read_text()))}
    assert rows['unprivileged']['key_line'] and rows['mp0']['key_line'] and rows['lxc.idmap']['key_line']
    assert not rows['hostname']['key_line'] and rows['hostname']['note']
    idmap = [r for r in explain.conf(parse.pct_config((FIX / 'pct_config_9005.txt').read_text())) if r['key'] == 'lxc.idmap']
    assert idmap[0]['note'] and not any(r['note'] for r in idmap[1:])  # Erklärung nur einmal
    assert explain.conf({'unprivileged': True}) is None  # Stand vor 0.5.6


def test_container_seite_host_einstellungen(client, monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_proxmox)
    set_pve(pve_host='10.0.0.5', pve_port='22')
    client.post('/scan')
    r = client.get('/container/9005?tab=host')
    assert r.status_code == 200 and '/etc/pve/lxc/9005.conf' in r.text and 'u 1000 1000 1' in r.text
    assert 'class="pl-key"' in r.text and 'mapping?art=umstieg' not in r.text
    r = client.get('/container/112?tab=host')
    assert 'Die Zeile unprivileged: 1 fehlt' in r.text and 'mapping?art=umstieg&amp;ct=112' in r.text
    assert 'vor-update' in r.text

# ---------------------------------------------------------------- Speicher-Ansicht
def test_speicher_ansicht(monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_proxmox)
    r = scan.run('10.0.0.5')
    v = view.storage(r)
    by = {s['source']: s for s in v['sources']}
    assert set(by) == {'/mnt/daten', '/mnt/teilen', '/srv/test/share', '/gibt/es/nicht'}
    assert by['/mnt/daten']['host_user'] == 'paperless' and by['/mnt/daten']['host_group'] == 'smbusers'
    assert by['/mnt/daten']['users'][0]['mapping'] == 'privilegiert'
    assert by['/gibt/es/nicht']['fs_kind'] == 'fehlt'
    assert by['/gibt/es/nicht']['users'][0]['seen'] is None
    # Freigaben auf dem Host ohne Container
    assert {m['target'] for m in v['unused']} == {'/mnt/nas', '/mnt/smb'}


def test_speicher_berechnet_bei_gestopptem_container():
    cfg = {'unprivileged': True, 'idmap': [], 'mounts': [
        {'key': 'mp0', 'source': '/mnt/daten', 'target': '/daten', 'kind': 'bind', 'readonly': True, 'options': {},
         'host_stat': {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 1000, 'gid': 1000, 'user': '', 'group': '',
                       'type': 'directory'}, 'acl': None, 'fs': None, 'fs_kind': 'lokal'}]}
    v = view.storage({'guests': [{'vmid': 200, 'type': 'lxc', 'name': 'x', 'status': 'stopped', 'config': cfg}]})
    u = v['sources'][0]['users'][0]
    assert u['seen']['live'] is False and u['nobody'] is True and u['readonly'] is True
    assert v['calculated'] is True and v['sources'][0]['problems'] == 1


def test_speicher_seite(client, monkeypatch):
    monkeypatch.setattr(ssh, 'run', fake_proxmox)
    set_pve(pve_host='10.0.0.5', pve_port='22')
    client.post('/scan')
    r = client.get('/speicher')
    assert r.status_code == 200
    for text in ('/mnt/daten', 'paperless', 'Weitere Freigaben auf dem Host', '/mnt/nas', 'Quelle fehlt'):
        assert text in r.text, text


def test_stat_unbekannte_namen():
    s = parse.stat('drwxr-xr-x|755|1000|1000|UNKNOWN|UNKNOWN|directory|/x\n')
    assert s['/x']['user'] == '' and s['/x']['group'] == ''
