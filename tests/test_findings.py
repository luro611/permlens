"""Befunde (AP 2.3) und Empfehlungen (AP 2.5)."""
from app.pve import findings
from conftest import set_pve  # noqa: E402

DIR = {'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 1000, 'type': 'directory'}


def lxc(vmid, name, unpriv, mounts, users=(), idmap=()):
    return {'vmid': vmid, 'name': name, 'type': 'lxc', 'status': 'running',
            'config': {'unprivileged': unpriv, 'idmap': list(idmap), 'mounts': mounts},
            'details': {'users': list(users), 'groups': [], 'stat': {}}}


def bind(key, source, target, host_stat=DIR, fs_kind='lokal', **kw):
    return {'key': key, 'source': source, 'target': target, 'kind': 'bind', 'host_stat': host_stat,
            'fs_kind': fs_kind, 'readonly': False, **kw}


ALICE = {'name': 'alice', 'uid': 1000, 'gid': 1000}
HI = {'passwd': [{'name': 'paperless', 'uid': 1000}], 'group': [],
      'subuid': [{'user': 'root', 'start': 100000, 'count': 65536}, {'user': 'luro', 'start': 165536, 'count': 65536}],
      'subgid': [{'user': 'root', 'start': 100000, 'count': 65536}]}


def scan_of(*guests):
    return {'host_info': HI, 'guests': list(guests)}


def keys(found):
    return {(f['key'], f['vmid']) for f in found}


def test_echte_faelle():
    s = scan_of(
        lxc(112, 'samba', False, [bind('mp0', '/mnt/appdata', '/mnt/appdata')], [{'name': 'luro', 'uid': 1000, 'gid': 1000}]),
        lxc(134, 'immich', False, [bind('mp0', '/mnt/pve/weg', '/mnt/x', host_stat=None, fs_kind='fehlt')]),
        lxc(9002, 'unpriv', True, [bind('mp1', '/srv/share', '/mnt/share')], [ALICE]),
        lxc(9005, 'idmap', True, [bind('mp1', '/srv/share', '/mnt/share')], [ALICE],
            idmap=[{'kind': k, 'ct': 1000, 'host': 1000, 'count': 1} for k in 'ug']),
        lxc(9004, 'nfs', True, [bind('mp0', '/mnt/nfs', '/mnt/test', host_stat=None, fs_kind='offline')]),
    )
    f = findings.collect(s)
    k = keys(f)
    assert ('fehlt', 134) in k and ('nobody', 9002) in k and ('nobody', 9005) not in k
    assert ('privilegiert', 112) in k and ('offline', 9004) in k
    assert ('subuid', None) in k and ('subgid', None) not in k  # subgid hat nur root
    assert ('uid-namen', None) in k  # 1000 heißt paperless (Host), luro (112), alice (9005)
    assert ('name-uid', None) in k   # alice: 9002 → 101000, 9005 → 1000
    assert ('setgid', None) not in k  # /srv/share hat setgid
    assert [x['level'] for x in f] == sorted((x['level'] for x in f), key=findings.LEVELS.index)
    assert findings.counts(f)['problem'] == 2


def test_nobody_empfehlung_mapping_bei_gemeinsamem_ordner():
    s = scan_of(lxc(9002, 'unpriv', True, [bind('mp1', '/srv/share', '/mnt/share')], [ALICE]),
                lxc(9001, 'priv', False, [bind('mp0', '/srv/share', '/mnt/share')]))
    f = next(x for x in findings.collect(s) if x['key'] == 'nobody')
    assert len(f['advice']) == 1 and f['advice'][0]['risk'] == 'risiko' and f['advice'][0]['where'] == 'host'
    cmd = f['advice'][0]['cmd']
    assert 'lxc.idmap: u 0 100000 1000\nlxc.idmap: u 1000 1000 1\nlxc.idmap: u 1001 101001 64535' in cmd
    assert '/etc/subuid: root:1000:1' in cmd and '/etc/subgid: root:1000:1' in cmd


def test_nobody_bei_root_ordner_nur_chown():
    root_dir = {**DIR, 'uid': 0, 'gid': 0, 'octal': '755'}
    s = scan_of(lxc(9002, 'unpriv', True, [bind('mp0', '/srv/eigen', '/mnt/test', host_stat=root_dir)], [ALICE]))
    f = next(x for x in findings.collect(s) if x['key'] == 'nobody')
    assert [a['cmd'] for a in f['advice']] == ['chown 100000:100000 /srv/eigen']


def test_setgid_fehlt_bei_gemeinsamem_ordner():
    plain = {**DIR, 'octal': '775'}
    s = scan_of(lxc(1, 'a', False, [bind('mp0', '/daten', '/d', host_stat=plain)]),
                lxc(2, 'b', False, [bind('mp0', '/daten', '/d', host_stat=plain)]))
    f = next(x for x in findings.collect(s) if x['key'] == 'setgid')
    assert f['advice'][0]['cmd'] == 'chmod g+s /daten' and f['advice'][0]['risk'] == 'vorsicht'


def test_empfehlungen_fuer_diagnose():
    g = lxc(9001, 'priv', False, [bind('mp1', '/srv/share', '/mnt/share')],
            [{'name': 'bob', 'uid': 1001, 'gid': 1001}])
    g['details']['groups'] = [{'name': 'alice', 'gid': 1000, 'members': []}]
    g['details']['stat'] = {'/mnt/share': DIR}
    res = {'read': True, 'write': False, 'cause': 'rechte', 'steps': []}
    tips = findings.for_diagnose(scan_of(g), g, {'name': 'bob', 'uid': 1001, 'gid': 1001}, '/mnt/share', res)
    assert tips[0]['cmd'] == 'usermod -aG alice bob' and tips[0]['where'] == 'ct'
    assert tips[-1]['risk'] == 'risiko'
    assert findings.for_diagnose(scan_of(g), g, {}, '/mnt/share', {'read': True, 'write': True}) == []


def test_seiten_zeigen_befunde(client, monkeypatch):
    from app.pve import scan
    s = scan_of(lxc(134, 'immich', False, [bind('mp0', '/mnt/pve/weg', '/mnt/x', host_stat=None, fs_kind='fehlt')]))
    s.update(host='10.0.0.5', finished='2026-10-19T10:00:00+00:00')
    monkeypatch.setattr(scan, 'latest', lambda i=None: s)
    from app import db
    set_pve(pve_host='10.0.0.5', pve_connected='1')
    assert '1 Problem' in client.get('/').text
    r = client.get('/probleme')
    assert 'Mount-Quelle fehlt: /mnt/pve/weg' in r.text and 'pct set 134 --delete mp0' in r.text
    assert 'Mount-Quelle fehlt' in client.get('/').text  # wichtigste Probleme auf der Übersicht
    assert 'href="/probleme"' in client.get('/diagnose').text
    assert 'Mount-Quelle fehlt' in client.get('/container/134').text
    assert client.get('/speicher').status_code == 200


def test_gleicher_name_auch_gegen_host():
    hi = {**HI, 'passwd': [{'name': 'luro', 'uid': 1001}, {'name': 'paperless', 'uid': 1000}, {'name': 'ceph', 'uid': 64045}]}
    s = {'host_info': hi, 'guests': [lxc(112, 'samba', False, [], [{'name': 'luro', 'uid': 1000, 'gid': 1000}])]}
    f = [x for x in findings.collect(s) if x['key'] == 'name-uid']
    assert len(f) == 1 and f[0]['title'] == ('„§“ hat verschiedene Nummern', 'luro')
    assert 'Host: 1001 → 1001' in f[0]['text'][1] and '112: 1000 → 1000' in f[0]['text'][1]


PAPERLESS = lxc(140, 'paperless', False, [bind('mp0', '/mnt/appdata', '/mnt/paperless-ngx')], [{'name': 'root', 'uid': 0, 'gid': 0}])
PAPERLESS['details']['stat'] = {'/mnt/paperless-ngx': DIR}
SAMBA = lxc(112, 'samba', False, [bind('mp0', '/mnt/appdata', '/mnt/appdata')], [{'name': 'luro', 'uid': 1000, 'gid': 1000}])


def test_nummern_ohne_namen():
    from app.pve import view
    s = scan_of(PAPERLESS, SAMBA)
    n = view.nameless(s, PAPERLESS)
    assert n == [{'uid': 1000, 'host_uid': 1000, 'paths': ['/mnt/paperless-ngx'],
                  'elsewhere': [('Host', 'paperless'), ('112', 'luro')]}]
    assert view.nameless(s, SAMBA) == []  # 1000 heißt dort luro


def test_benutzer_seite(client, monkeypatch):
    from app.pve import scan, view
    hi = {**HI, 'passwd': [{'name': 'luro', 'uid': 1001}, {'name': 'paperless', 'uid': 1000}, {'name': 'ceph', 'uid': 64045}]}
    s = {'host_info': hi, 'guests': [PAPERLESS, SAMBA], 'host': '10.0.0.5', 'finished': '2026-10-19T10:00:00+00:00'}
    p = view.people(s)
    assert p['names'][0]['name'] == 'luro' and p['names'][0]['differs']  # verschiedene Nummern zuerst
    assert 'ceph' not in {n['name'] for n in p['names']}
    n1000 = next(x for x in p['numbers'] if x['host_uid'] == 1000)
    assert n1000['sources'] == ['/mnt/appdata'] and n1000['differs']
    monkeypatch.setattr(scan, 'latest', lambda i=None: s)
    r = client.get('/benutzer')
    assert r.status_code == 200 and 'verschiedene Nummern' in r.text and '/mnt/appdata' in r.text
    r = client.get('/container/140?tab=benutzer')
    assert 'Nummern ohne Namen' in r.text and 'paperless · Host' in r.text


def test_benutzer_und_gruppen_auf_uebersicht(client, monkeypatch):
    from app import db
    from app.pve import scan, view
    g = lxc(112, 'samba', False, [], [{'name': 'root', 'uid': 0, 'gid': 0}, {'name': 'luro', 'uid': 1000, 'gid': 1000},
                                      {'name': 'www-data', 'uid': 33, 'gid': 33}])
    g['details']['groups'] = [{'name': 'luro', 'gid': 1000, 'members': []},
                              {'name': 'smbusers', 'gid': 1500, 'members': ['luro']},
                              {'name': 'sudo', 'gid': 27, 'members': ['luro']}]
    a = view.accounts(g)
    assert [u['name'] for u in a['users']] == ['luro'] and [x['name'] for x in a['groups']] == ['smbusers']
    nur_root = lxc(116, 'kuma', True, [], [{'name': 'root', 'uid': 0, 'gid': 0}])
    s = {'host_info': {'passwd': [{'name': 'paperless', 'uid': 1000}], 'group': []}, 'guests': [g, nur_root],
         'host': '10.0.0.5', 'finished': '2026-10-19T10:00:00+00:00'}
    monkeypatch.setattr(scan, 'latest', lambda i=None: s)
    set_pve(pve_host='10.0.0.5', pve_connected='1')
    r = client.get('/')
    assert '>luro</span>' in r.text and '>smbusers</span>' in r.text and 'nur root' in r.text
    assert 'www-data' not in r.text
    assert 'heißt dort paperless' in client.get('/container/112?tab=benutzer').text
