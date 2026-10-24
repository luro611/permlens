"""Klartext für Benutzer, Gruppen und Ordner-Rechte (0.5.1, Wunsch von Lutz: „die Probleme von Nicht-Nerds“)."""
from app.pve import explain, view

ST = {'type': 'directory', 'mode': 'drwxrwsr-x', 'octal': '2775', 'uid': 1000, 'gid': 2000}
IDMAP = [('u', 0, 100000, 1000), ('u', 1000, 1000, 1), ('u', 1001, 101001, 64535),
         ('g', 0, 100000, 2000), ('g', 2000, 2000, 1), ('g', 2001, 102001, 63535)]
CFG = {'unprivileged': True, 'idmap': [{'kind': k, 'ct': c, 'host': h, 'count': n} for k, c, h, n in IDMAP],
       'mounts': [{'key': 'mp0', 'source': '/srv/share', 'target': '/mnt/share', 'kind': 'bind', 'readonly': False,
                   'options': {}, 'host_stat': {**ST}, 'acl': None, 'fs': None, 'fs_kind': 'lokal'},
                  {'key': 'mp1', 'source': '/srv/ro', 'target': '/mnt/ro', 'kind': 'bind', 'readonly': True,
                   'options': {}, 'host_stat': {**ST}, 'acl': None, 'fs': None, 'fs_kind': 'lokal'}]}
GUEST = {'vmid': 9005, 'type': 'lxc', 'name': 't', 'status': 'running', 'config': CFG,
         'details': {'users': [{'name': 'root', 'uid': 0, 'gid': 0, 'home': '/root', 'shell': '/bin/bash'},
                               {'name': 'alice', 'uid': 1000, 'gid': 1000, 'home': '/home/alice', 'shell': '/bin/bash'},
                               {'name': 'bob', 'uid': 1001, 'gid': 1001, 'home': '/home/bob', 'shell': '/bin/bash'},
                               {'name': 'paperless', 'uid': 1002, 'gid': 2000, 'home': '/opt',
                                'shell': '/usr/sbin/nologin'},
                               {'name': 'www-data', 'uid': 33, 'gid': 33, 'home': '/var/www', 'shell': '/usr/sbin/nologin'}],
                     'groups': [{'name': 'root', 'gid': 0, 'members': []}, {'name': 'alice', 'gid': 1000, 'members': []},
                                {'name': 'bob', 'gid': 1001, 'members': []},
                                {'name': 'medien', 'gid': 2000, 'members': ['bob']}],
                     'stat': {'/': {**ST, 'uid': 0, 'gid': 0, 'mode': 'drwxr-xr-x', 'octal': '755'},
                              '/mnt': {**ST, 'uid': 0, 'gid': 0, 'mode': 'drwxr-xr-x', 'octal': '755'},
                              '/mnt/share': {**ST}, '/mnt/ro': {**ST}}}}


def users():
    return {u['name']: u for u in view.container({'guests': [GUEST]}, GUEST)['users']}


def texts(parts):
    return ' '.join(p[0] for p in parts)


def test_rollen_in_klartext():
    u = users()
    assert 'Verwalter' in texts(u['root']['role']) and 'keine Sonderrechte' in texts(u['root']['role'])
    assert 'Persönliches Konto' in texts(u['alice']['role'])
    assert 'durchgereicht' in texts(u['alice']['role'])  # 1000 → 1000
    assert ('Ihm gehören diese eingehängten Ordner: §.', '/mnt/share, /mnt/ro') in u['alice']['role']
    assert 'Dienst-Konto' in texts(u['paperless']['role'])
    assert ('Der Name passt zu §. Vermutlich hat das Programm diesen Benutzer angelegt.', 'paperless-ngx') in u['paperless']['role']
    assert ('Auf dem Proxmox wird daraus die Nummer §. Was dieser Benutzer in eingehängte Ordner schreibt, '
            'gehört dort der Nummer §.', 101001, 101001) in u['bob']['role']
    assert u['www-data']['role'] == [(explain.SYSTEM['www-data'],)] and u['www-data']['folders'] == []


def test_rechte_je_ordner_mit_begruendung():
    u = users()
    share = {f['target']: f for f in u['alice']['folders']}['/mnt/share']
    assert share['read'] and share['write'] and share['perm'] == 'rwx'
    assert share['why'] == [('§ ist der Besitzer des Ordners. Der Besitzer darf hier:', 'alice'), ('lesen und schreiben.',)]
    bob = {f['target']: f for f in u['bob']['folders']}
    assert bob['/mnt/share']['write'] and 'Gruppe §' in bob['/mnt/share']['why'][0][0]
    assert bob['/mnt/share']['why'][0][1] == 'medien'  # Name statt Nummer
    ro = bob['/mnt/ro']
    assert ro['read'] and not ro['write'] and 'nur zum Lesen eingehängt' in texts(ro['why'])
    root = {f['target']: f for f in u['root']['folders']}['/mnt/share']
    assert root['write'] and 'weil der Besitzer des Ordners im Container bekannt ist' in texts(root['why'])
    paperless = {f['target']: f for f in u['paperless']['folders']}['/mnt/share']
    assert paperless['write'] and paperless['why'][0][1:] == ('medien', 'paperless')  # Hauptgruppe zählt auch


def test_nobody_grund_zuerst():
    res = {'read': True, 'write': False, 'cause': 'nobody', 'hints': [],
           'steps': [{'path': '/mnt/x', 'ok': False, 'need': 'wx', 'why': ('andere: §', 'r-x')}]}
    a = explain.folder_access('alice', res, {}, True)
    assert a['why'][0][0].startswith('Der Ordner gehört auf dem Proxmox einer Nummer') and len(a['why']) == 2


def test_gruppen_erklaert():
    g = {x['name']: x for x in view.container({'guests': [GUEST]}, GUEST)['groups']}
    assert 'Eigene Gruppe von §' in g['alice']['role'][0][0]
    assert 'Gemeinsame Gruppe' in g['medien']['role'][0][0]
    assert ('Ihr gehören diese eingehängten Ordner: §.', '/mnt/share, /mnt/ro') in g['medien']['role']


def test_gestoppter_container_zeigt_keine_rechte():
    stopped = {**GUEST, 'status': 'stopped'}
    assert all(u['folders'] == [] for u in view.container({'guests': [stopped]}, stopped)['users'])
