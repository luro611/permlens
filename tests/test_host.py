"""Seite „Host“ (0.2.3): Speicher aus storage.cfg, Netzfreigaben, Host-Ordner, subuid/subgid. Nur lesen."""
from app.pve import parse, scan, view

STORAGE = """dir: local
\tpath /var/lib/vz
\tcontent vztmpl,iso,backup

lvmthin: local-lvm
\tthinpool data
\tvgname pve
\tcontent images,rootdir

nfs: nas-backup
\texport /volume1/Backup
\tpath /mnt/pve/nas-backup
\tserver 10.0.0.250
\tcontent backup,iso

cifs: syno
\tserver 10.0.0.2
\tshare daten
\tusername luro
\tpassword geheim
\tcontent images
\tdisable 1

dir: appdata
\tpath /mnt/appdata
\tcontent images
"""


def scan_data():
    hi = {'storage': parse.storage_cfg(STORAGE),
          'mounts': [{'target': '/mnt/pve/nas-backup', 'source': '10.0.0.250:/volume1/Backup', 'fstype': 'nfs', 'options': ''},
                     {'target': '/mnt/von-hand', 'source': '10.0.0.250:/volume1/x', 'fstype': 'nfs', 'options': ''}],
          'passwd': [{'name': 'luro', 'uid': 1001}, {'name': 'ceph', 'uid': 64045}],
          'group': [{'name': 'smbusers', 'gid': 1000, 'members': ['luro']}],
          'subuid': [{'user': 'root', 'start': 100000, 'count': 65536}, {'user': 'luro', 'start': 165536, 'count': 65536},
                     {'user': 'root', 'start': 1000, 'count': 1}],
          'subgid': []}
    g = [{'vmid': 112, 'name': 'samba', 'type': 'lxc', 'status': 'running',
          'config': {'unprivileged': False, 'raw': {'rootfs': 'local-lvm:vm-112-disk-0,size=8G'}, 'mounts': [
              {'key': 'mp0', 'source': '/mnt/appdata', 'target': '/mnt/appdata', 'kind': 'bind'}]}},
         {'vmid': 9005, 'name': 'idmap', 'type': 'lxc', 'status': 'running',
          'config': {'unprivileged': True, 'raw': {'rootfs': 'local-lvm:vm-9005-disk-0'},
                     'idmap': [{'kind': 'u', 'ct': 0, 'host': 100000, 'count': 1000}, {'kind': 'u', 'ct': 1000, 'host': 1000, 'count': 1}],
                     'mounts': [{'key': 'mp0', 'source': '/mnt/von-hand', 'target': '/mnt/x', 'kind': 'bind'}]}}]
    return {'host': '10.0.0.5', 'finished': '2026-10-19T10:00:00+00:00', 'host_info': hi, 'guests': g}


def test_storage_cfg_ohne_passwort():
    st = parse.storage_cfg(STORAGE)
    syno = next(s for s in st if s['id'] == 'syno')
    assert 'password' not in syno['props'] and syno['props']['username'] == 'luro'


def test_host_auswertung():
    h = view.host(scan_data())
    by = {s['id']: s for s in h['storages']}
    assert [u['vmid'] for u in by['local-lvm']['used']] == [112, 9005]
    assert by['nas-backup']['mounted'] and not by['nas-backup']['used'] and by['nas-backup']['backup_only']
    assert by['nas-backup']['where'] == '10.0.0.250:/volume1/Backup'
    assert by['syno']['disabled'] and by['syno']['mounted'] is False
    assert [u['vmid'] for u in by['appdata']['used']] == [112]
    assert [m['target'] for m in h['manual']] == ['/mnt/von-hand']
    assert [f['source'] for f in h['folders']] == ['/mnt/von-hand']
    assert [u['name'] for u in h['users']] == ['luro']  # ceph ist eine Systemnummer
    sub = {(e['user'], e['start']): e['containers'] for e in h['subuid']}
    assert sub[('root', 100000)] == [9005] and sub[('root', 1000)] == [9005] and sub[('luro', 165536)] == []


def test_host_seite(client, monkeypatch):
    monkeypatch.setattr(scan, 'latest', lambda i=None: scan_data())
    r = client.get('/host')
    assert r.status_code == 200 and 'nas-backup' in r.text and 'Von keinem Container genutzt' in r.text
    assert 'Von Hand eingehängte Netzfreigaben' in r.text and 'geheim' not in r.text
    assert 'niemandem (Proxmox nutzt nur root)' in r.text


def test_scan_liest_storage_cfg():
    assert scan.HOST_CMDS['storage'] == ['cat', '/etc/pve/storage.cfg']
