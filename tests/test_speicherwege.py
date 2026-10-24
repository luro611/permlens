"""AP 2.4: Speicher-Wege (lxc.mount.entry, eigene Mounts im Container, Samba-Freigaben, SMB-Optionen)."""
from app.pve import parse, scan, ssh, view

TESTPARM = """# Global parameters
[global]
	server role = standalone server
	workgroup = WORKGROUP

[homes]
	browseable = No
	valid users = %S

[appdata]
	force group = luro
	force user = luro
	path = /mnt/appdata
	read only = No
	valid users = luro

[printers]
	path = /var/spool/samba
"""


def test_testparm():
    r = parse.testparm(TESTPARM)
    assert r['global']['workgroup'] == 'WORKGROUP'
    assert [s['name'] for s in r['shares']] == ['homes', 'appdata']
    assert r['shares'][1]['force user'] == 'luro' and r['shares'][1]['read only'] == 'No'


def test_lxc_mount_entry():
    cfg = parse.pct_config('mp0: /mnt/a,mp=/mnt/a\nlxc.mount.entry: /mnt/nas mnt/nas none bind,create=dir,ro 0 0\n'
                           'lxc.mount.entry: /dev/net dev/net none bind,create=dir 0 0\n')
    assert [m['key'] for m in cfg['mounts']] == ['mp0', 'lxc.mount.entry', 'lxc.mount.entry']
    e = cfg['mounts'][1]
    assert e['source'] == '/mnt/nas' and e['target'] == '/mnt/nas' and e['entry'] and e['readonly'] and e['kind'] == 'bind'


def test_mount_opts():
    assert parse.mount_opts('rw,uid=1000,gid=10,file_mode=0755,noforceuid') == {
        'rw': True, 'uid': '1000', 'gid': '10', 'file_mode': '0755', 'noforceuid': True}


def test_scan_liest_eigene_mounts_und_samba(monkeypatch):
    findmnt_ct = ('{"filesystems": [{"target": "/", "source": "x", "fstype": "ext4", "options": "rw", "children": ['
                  '{"target": "/mnt/share", "source": "10.0.0.2:/v", "fstype": "nfs", "options": "rw"},'
                  '{"target": "/mnt/nas", "source": "//nas/daten", "fstype": "cifs", "options": "rw,uid=1000,gid=1000"}]}]}')

    def run(host, args, port=22, timeout=75):
        if args[-len(scan.FINDMNT):] == scan.FINDMNT:
            return ssh.Result(0, findmnt_ct, '')
        if args[-2:] == ['testparm', '-s']:
            return ssh.Result(0, TESTPARM, '')
        return ssh.Result(0, '', '')
    monkeypatch.setattr(ssh, 'run', run)
    guest = {'vmid': 112, 'config': {'mounts': [{'target': '/mnt/share', 'source': '/srv/share', 'kind': 'bind'}]}}
    d = scan._details('h', 22, guest)
    assert [m['target'] for m in d['own_mounts']] == ['/mnt/nas']  # /mnt/share kommt vom Host
    assert d['samba']['shares'][1]['name'] == 'appdata'


def test_mount_entry_wird_nicht_als_fehlend_gemeldet(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    guests = [{'vmid': 1, 'config': {'mounts': [{'key': 'lxc.mount.entry', 'source': '/mnt/nas', 'target': '/mnt/nas',
                                                  'kind': 'bind', 'entry': True}]}}]
    calls = []
    monkeypatch.setattr(ssh, 'run', lambda h, a, p=22, timeout=75: calls.append(a) or ssh.Result(126, '', ''))
    with ThreadPoolExecutor(2) as pool:
        scan._mount_info('h', 22, guests, [{'target': '/mnt/nas', 'source': '10.0.0.2:/v', 'fstype': 'nfs', 'options': ''}], pool)
    m = guests[0]['config']['mounts'][0]
    assert m['fs_kind'] == 'nfs' and m['host_unchecked'] and not calls  # kein stat, den der Wächter ablehnen würde


def test_container_seite_freigaben(client, monkeypatch):
    g = {'vmid': 112, 'name': 'samba', 'type': 'lxc', 'status': 'running',
         'config': {'unprivileged': False, 'idmap': [], 'mounts': [
             {'key': 'mp0', 'source': '/mnt/appdata', 'target': '/mnt/appdata', 'kind': 'bind', 'fs_kind': 'lokal',
              'host_stat': {'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 1000, 'user': '', 'group': '',
                            'type': 'directory'}}]},
         'details': {'users': [{'name': 'luro', 'uid': 1000, 'gid': 1000, 'home': '', 'shell': '', 'gecos': ''}],
                     'groups': [], 'stat': {}, 'samba': parse.testparm(TESTPARM),
                     'own_mounts': [{'target': '/mnt/nas', 'source': '//nas/daten', 'fstype': 'cifs', 'options': 'rw,uid=1000,gid=1000'}]}}
    s = {'host': 'h', 'finished': '2026-10-19T10:00:00+00:00', 'host_info': {}, 'guests': [g]}
    monkeypatch.setattr(scan, 'latest', lambda i=None: s)
    v = view.container(s, g)
    assert [x['name'] for x in v['shares']] == ['appdata'] and v['shares'][0]['as_uid'] == 1000
    assert v['shares'][0]['writable'] and v['shares'][0]['mount']['source'] == '/mnt/appdata'
    r = client.get('/container/112?tab=freigaben')
    assert '[appdata]' in r.text and 'schreibt im Container als luro' in r.text
    r = client.get('/container/112?tab=mounts')
    assert 'Vom Container selbst eingehängt' in r.text and 'Nummer 1000 (Gruppe 1000)' in r.text
    from app.pve import findings
    assert any(f['key'] == 'samba' for f in findings.collect(s))
