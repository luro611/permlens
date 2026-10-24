"""Phase 4, AP 4.2: Bauplan für einen neuen unprivilegierten Container."""
import pytest

from app import db
from app.pve import bauplan, scan

ST = {'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 1000, 'type': 'directory'}
SCAN = {'host': '10.0.0.8', 'guests': [
    {'vmid': 9005, 'name': 'idmap', 'type': 'lxc', 'status': 'running',
     'config': {'unprivileged': True, 'mounts': [{'key': 'mp1', 'kind': 'bind', 'source': '/srv/share', 'target': '/mnt/share',
                                                  'host_stat': ST}],
                'idmap': [{'kind': k, 'ct': c, 'host': h, 'count': n} for k in 'ug'
                          for c, h, n in ((0, 100000, 1000), (1000, 1000, 1), (1001, 101001, 64535))]}},
    {'vmid': 9001, 'name': 'priv', 'type': 'lxc', 'status': 'running',
     'config': {'unprivileged': False, 'mounts': [{'key': 'mp0', 'kind': 'bind', 'source': '/srv/root-only', 'target': '/mnt/x',
                                                   'host_stat': {**ST, 'uid': 0, 'gid': 0, 'octal': '755', 'mode': 'drwxr-xr-x'}}]}}],
    'host_info': {'subuid': [{'user': 'root', 'start': 100000, 'count': 65536}],
                  'subgid': [{'user': 'root', 'start': 100000, 'count': 65536}, {'user': 'root', 'start': 1000, 'count': 1}]}}


def test_bekannte_ordner():
    assert [f['path'] for f in bauplan.known_folders(SCAN)] == ['/srv/root-only', '/srv/share']


def test_bauplan_paperless():
    p = bauplan.make(SCAN, {'src0': '/srv/share', 'dst0': '/data', 'vmid': '160', 'app': 'paperless'})
    assert not p['errors'] and (p['uid'], p['gid']) == (1000, 1000)  # vom Besitzer des Ordners übernommen
    assert p['conf'][0] == 'mp0: /srv/share,mp=/data'
    assert 'lxc.idmap: u 1000 1000 1' in p['conf'] and 'lxc.idmap: g 1001 101001 64535' in p['conf']
    assert p['sub_u'] == ['root:1000:1'] and p['sub_g'] == []  # subgid hat 1000 schon
    assert p['env'] == ['USERMAP_UID=1000', 'USERMAP_GID=1000']
    assert p['folders'][0]['check'] == {'read': True, 'write': True} and p['folders'][0]['ct_owner'] == (1000, 1000)
    assert "cat >> /etc/pve/lxc/160.conf <<'EOF'" in p['cmds']['conf']
    assert "grep -qx 'root:1000:1' /etc/subuid" in p['cmds']['subuid'] and p['cmds']['subgid'] == ''
    assert {s['vmid']: s['ids'] for s in p['shared']} == {9005: 'Benutzer 1000, Gruppe 1000', 9001: 'Benutzer 1000, Gruppe 1000'}
    assert '# 3) Für den Docker-Stack (paperless-ngx)' in p['text']


def test_unbekannter_ordner_braucht_nummern():
    p = bauplan.make(SCAN, {'src0': '/mnt/neu'})
    assert 'Benutzer- und Gruppennummer angeben' in p['errors'][0][0]
    p = bauplan.make(SCAN, {'src0': '/mnt/neu', 'uid': '1000', 'gid': '2000', 'gids': '2001', 'app': 'docker'})
    assert not p['errors'] and p['env'] == ['PUID=1000', 'PGID=2000'] and p['folders'][0]['check'] is None
    assert 'lxc.idmap: g 2000 2000 2' in p['conf']  # 2000 und 2001 zusammengefasst


def test_nur_lesen_und_falsche_gruppe():
    p = bauplan.make(SCAN, {'src0': '/srv/share', 'ro0': '1', 'uid': '1001', 'gid': '1001'})
    assert p['conf'][0].endswith(',ro=1')
    assert p['folders'][0]['check']['write'] is False


@pytest.mark.parametrize('params, fehler', [
    ({}, 'Mindestens einen'),
    ({'src0': '/srv/share', 'vmid': '9005'}, 'gibt es schon'),
    ({'src0': '/srv/share', 'vmid': '12'}, 'ungültig'),
    ({'src0': 'relativ'}, 'ungültig'),
    ({'src0': '/mnt/a b', 'uid': '1000', 'gid': '1000'}, 'ungültig'),
    ({'src0': '/mnt/a,b', 'uid': '1000', 'gid': '1000'}, 'ungültig'),
    ({'src0': '/srv/root-only'}, '1 bis 65533'),
    ({'src0': '/srv/share', 'uid': '65534', 'gid': '1000'}, '1 bis 65533'),
    ({'src0': '/srv/share', 'gids': 'abc'}, 'Weitere Gruppen'),
    ({'src0': '/srv/share', 'src1': '/srv/root-only', 'dst1': '/srv/share'}, 'dasselbe Ziel'),
])
def test_fehler(params, fehler):
    assert any(fehler in e[0] for e in bauplan.make(SCAN, params)['errors'])


def test_seite_und_download(client):
    scan.save({**SCAN, 'started': '', 'finished': db.now(), 'error': ''})
    r = client.get('/mapping')
    assert r.status_code == 200 and '/srv/share' in r.text and 'Bauplan erstellen' in r.text
    r = client.get('/mapping?src0=/srv/share&dst0=/data&vmid=160&app=paperless')
    assert 'Schritt für Schritt' in r.text and 'USERMAP_UID=1000' in r.text and 'root:1000:1' in r.text
    r = client.get('/mapping/bauplan.txt?src0=/srv/share&dst0=/data&vmid=160&app=paperless')
    assert r.status_code == 200 and 'permlens-bauplan-160.txt' in r.headers['content-disposition']
    assert r.text.startswith('# PermLens-Bauplan') and 'lxc.idmap: u 1000 1000 1' in r.text
    r = client.get('/mapping/bauplan.txt?src0=relativ')
    assert r.status_code == 400


# ---------------------------------------------------------------- AP 4.3: bestehender Container
UNPRIV = {'vmid': 9002, 'name': 'std', 'type': 'lxc', 'status': 'running',
          'config': {'unprivileged': True, 'mounts': [
              {'key': 'mp0', 'kind': 'bind', 'source': '/srv/bind', 'target': '/mnt/test', 'host_stat': {**ST, 'uid': 0, 'gid': 0}},
              {'key': 'mp1', 'kind': 'bind', 'source': '/srv/share', 'target': '/mnt/share', 'host_stat': ST}]},
          'details': {'users': [{'name': 'alice', 'uid': 1000, 'gid': 1000}], 'groups': [{'name': 'alice', 'gid': 1000, 'members': []}]}}
SCAN2 = {**SCAN, 'guests': SCAN['guests'] + [UNPRIV]}


def test_vorschlag_bestehender_container():
    p = bauplan.existing_plan(SCAN2, 9002, {})
    assert not p['errors'] and p['sel_u'] == {1000} and p['sel_g'] == {1000}  # root (0) nie vorgeschlagen
    assert p['added_u'] == [1000] and 'lxc.idmap: u 1000 1000 1' in p['idmap']
    assert [m['ct_now'] for m in p['mounts']] == [(None, None), (None, None)]
    assert p['mounts'][1]['ct_after'] == (1000, 1000) and p['mounts'][0]['ct_after'] == (65534, 65534)
    assert ('u', 1000, 101000, 'alice') in p['moved']  # was alice bisher anlegte, liegt bei 101000
    prune = r'\( -path /var/lib/lxc/9002/rootfs/mnt/test -o -path /var/lib/lxc/9002/rootfs/mnt/share \) -prune -o '
    assert f'find /var/lib/lxc/9002/rootfs -xdev {prune}-uid 101000 -exec chown -h 1000 {{}} +' in p['cmds']['fix']
    assert f'find /var/lib/lxc/9002/rootfs -xdev {prune}-uid 1000 -exec chown -h 101000 {{}} +' in p['cmds']['undo']
    assert 'find /srv/share -xdev -uid 101000 -exec chown -h 1000 {} +' in p['cmds']['fix']
    assert 'cat /root/9002.conf.neu > /etc/pve/lxc/9002.conf' in p['cmds']['conf']
    assert p['cmds']['subuid'] == "(grep -qx 'root:1000:1' /etc/subuid || echo 'root:1000:1' >> /etc/subuid)"
    assert '/srv/share' not in p['cmds']['undo'] and 'cat /root/9002.conf.vor-permlens' in p['cmds']['undo']
    assert {s['vmid'] for s in p['shared']} >= {9005}


def test_vorschlag_auswahl_und_nichts_zu_tun():
    p = bauplan.existing_plan(SCAN2, 9002, {'chosen': '1', 'u': ['1000'], 'g': []})
    assert p['added_g'] == [] and p['added_u'] == [1000]
    assert bauplan.existing_plan(SCAN2, 9002, {'chosen': '1'}).get('nothing')
    assert bauplan.existing_plan(SCAN2, 9005, {}).get('nothing')  # 9005 reicht 1000 schon durch
    assert 'privilegiert' in bauplan.existing_plan(SCAN2, 9001, {})['errors'][0][0]
    assert 'Zusätzliche' in bauplan.existing_plan(SCAN2, 9002, {'more_u': 'x'})['errors'][0][0]


def test_seite_bestehend(client):
    scan.save({**SCAN2, 'started': '', 'finished': db.now(), 'error': ''})
    r = client.get('/mapping?art=bestehend&ct=9002')
    assert 'Dateien nachziehen' in r.text and 'pct shutdown 9002' in r.text and 'Zurück zum alten Stand' in r.text
    r = client.get('/probleme')
    assert '/mapping?art=bestehend&amp;ct=9002' in r.text or '/mapping?art=bestehend&ct=9002' in r.text


# ---------------------------------------------------------------- AP 4.4: Umstieg privilegiert → unprivilegiert
PRIV = {'vmid': 9003, 'name': 'samba', 'type': 'lxc', 'status': 'running',
        'config': {'unprivileged': False, 'raw': {'rootfs': 'local-lvm:vm-9003-disk-0,size=4G', 'features': 'nesting=1'},
                   'mounts': [{'key': 'mp0', 'kind': 'bind', 'source': '/srv/share', 'target': '/mnt/share', 'host_stat': ST},
                              {'key': 'mp1', 'kind': 'bind', 'source': '/srv/rootdata', 'target': '/data', 'host_stat': {**ST, 'uid': 0, 'gid': 0}}]}}
SCAN3 = {**SCAN, 'guests': SCAN['guests'] + [PRIV, {'vmid': 9103, 'name': 'x', 'type': 'lxc', 'config': {}}],
         'host_info': {**SCAN['host_info'], 'storage': [
             {'id': 'local', 'type': 'dir', 'props': {'path': '/var/lib/vz', 'content': 'iso,vztmpl,backup'}},
             {'id': 'local-lvm', 'type': 'lvmthin', 'props': {'content': 'rootdir,images'}}]}}


def test_umstieg():
    p = bauplan.migration_plan(SCAN3, 9003, {})
    assert not p['errors'] and p['new'] == '9104' and p['store'] == 'local'  # 9103 ist belegt
    assert p['sel_u'] == {1000} and p['sel_g'] == {1000}
    assert p['cmds']['backup'] == 'vzdump 9003 --storage local --mode stop --compress zstd'
    assert 'pct restore 9104 "$VOL" --unprivileged 1 --storage local-lvm --ignore-unpack-errors 1' in p['cmds']['restore']
    assert "cat /root/9104.conf.neu > /etc/pve/lxc/9104.conf" in p['cmds']['idmap']
    assert '-uid 101000 -exec chown -h 1000' in p['cmds']['fix'] and '-path /var/lib/lxc/9104/rootfs/data' in p['cmds']['fix']
    assert p['cmds']['docker'] == 'pct set 9104 --features nesting=1,keyctl=1'
    assert p['cmds']['back'] == 'pct shutdown 9104 && pct set 9104 --onboot 0 && pct set 9003 --onboot 1 && pct start 9003'
    assert [m['src'] for m in p['root_owned']] == ['/srv/rootdata']
    assert [m.get('ct_after') for m in p['mounts']] == [(1000, 1000), (65534, 65534)]


def test_umstieg_fehler():
    assert 'schon unprivilegiert' in bauplan.migration_plan(SCAN3, 9005, {})['errors'][0][0]
    assert 'schon vergeben' in bauplan.migration_plan(SCAN3, 9003, {'new': '9005'})['errors'][0][0]
    assert 'kein Speicher' in bauplan.migration_plan({**SCAN3, 'host_info': {}}, 9003, {})['errors'][0][0]
    p = bauplan.migration_plan(SCAN3, 9003, {'chosen': '1'})  # nichts durchreichen
    assert p['idmap'] == [] and p['cmds']['fix'] == '' and p['cmds']['idmap'] == ''


def test_seite_umstieg(client):
    scan.save({**SCAN3, 'started': '', 'finished': db.now(), 'error': ''})
    r = client.get('/mapping?art=umstieg&ct=9003')
    assert 'vzdump 9003' in r.text and 'Zurück zum alten Container' in r.text and 'gehören auf dem Host root' in r.text
