"""Docker-Einblick (AP 6.2): Apps im LXC, als wer sie schreiben, Probleme, Container-Seite und Prüfen."""
import json

import pytest

from app import db
from app.pve import docker, findings, scan, ssh, view
from conftest import set_pve  # noqa: E402

STAT_APP = {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 1000, 'gid': 1000, 'user': 'alice', 'group': 'alice',
            'type': 'directory'}
STAT_ROOT = {**STAT_APP, 'uid': 0, 'gid': 0, 'user': 'root', 'group': 'root'}
DIR = {'mode': 'drwxr-xr-x', 'octal': '755', 'uid': 0, 'gid': 0, 'user': 'root', 'group': 'root', 'type': 'directory'}


def app(name='paperless', **kw):
    a = {'name': name, 'image': 'ghcr.io/paperless-ngx/paperless-ngx:2', 'state': 'running', 'status': 'Up',
         'user': '', 'privileged': False, 'userns': '', 'env': {}, 'labels': {'com.docker.compose.project': 'paperless'},
         'mounts': [{'type': 'bind', 'source': '/srv/app', 'destination': '/data', 'rw': True},
                    {'type': 'volume', 'source': '/var/lib/docker/volumes/cfg/_data', 'destination': '/config', 'rw': True}],
         'processes': [{'uid': 0, 'gid': 0, 'comm': 's6-svscan'}, {'uid': 1000, 'gid': 1000, 'comm': 'gunicorn'}]}
    return {**a, **kw}


def guest(apps, stat=None, unprivileged=True):
    return {'vmid': 9006, 'name': 'ppm-test-tool', 'type': 'lxc', 'status': 'running',
            'config': {'unprivileged': unprivileged, 'idmap': [], 'mounts': []},
            'details': {'users': [{'name': 'root', 'uid': 0, 'gid': 0}, {'name': 'alice', 'uid': 1000, 'gid': 1000}],
                        'groups': [{'name': 'root', 'gid': 0, 'members': []}, {'name': 'alice', 'gid': 1000, 'members': []}],
                        'stat': {'/': DIR, '/srv': DIR, '/srv/app': STAT_APP, '/var': DIR, '/var/lib': DIR,
                                 '/var/lib/docker': DIR, '/var/lib/docker/volumes': DIR,
                                 '/var/lib/docker/volumes/cfg': DIR, '/var/lib/docker/volumes/cfg/_data': STAT_ROOT,
                                 **(stat or {})},
                        'docker': {'apps': apps, 'error': '', 'more': 0}}}


# ---------------------------------------------------------------- als wer schreibt die App?
@pytest.mark.parametrize('a, erwartet', [
    (app(), (1000, 1000, 'prozesse')),                                                 # root startet, gunicorn arbeitet
    (app(processes=[{'uid': 0, 'gid': 0, 'comm': 'nginx'}]), (0, 0, 'prozesse')),
    (app(processes=None, env={'PUID': '1001', 'PGID': '2000'}), (1001, 2000, 'variable')),
    (app(processes=None, env={'USERMAP_UID': '1000'}), (1000, 1000, 'variable')),
    (app(processes=None, user='33:33'), (33, 33, 'user')),
    (app(processes=None, user='node'), (None, None, 'user')),
    (app(processes=None), (0, 0, 'standard')),
])
def test_writer(a, erwartet):
    w = docker.writer(a)
    assert (w['uid'], w['gid'], w['origin']) == erwartet


def test_writer_puid_wirkt_nicht():
    w = docker.writer(app(env={'PUID': '1001'}))
    assert w['uid'] == 1000 and w['top_differs'] and w['origin_var'] == 'PUID'


# ---------------------------------------------------------------- Einlesen
class Proxmox:
    def __init__(self, antworten):
        self.antworten, self.calls = antworten, []

    def __call__(self, host, args, port=22, timeout=None, data=None):
        self.calls.append(args)
        for key, out in self.antworten.items():
            if args[:len(key)] == list(key):
                return ssh.Result(0, out, '')
        return ssh.Result(1, '', 'unbekannt')


def test_collect_ohne_docker(monkeypatch):
    monkeypatch.setattr(ssh, 'run', Proxmox({('docker-ps',): '{"docker": false, "error": "Failed to exec"}'}))
    assert docker.collect('h', 22, 9001, scan.STAT, 10) is None


def test_collect(monkeypatch):
    inspect = {k: v for k, v in app().items() if k not in ('processes', 'status')}
    p = Proxmox({('docker-ps',): json.dumps({'docker': True, 'apps': [
                     {'name': 'paperless', 'image': 'x', 'state': 'running', 'status': 'Up'},
                     {'name': 'redis', 'image': 'redis', 'state': 'exited', 'status': 'Exited'}]}),
                 ('docker-inspect', '9006', 'paperless'): json.dumps(inspect),
                 ('docker-inspect', '9006', 'redis'): json.dumps({**inspect, 'name': 'redis', 'state': 'exited', 'mounts': []}),
                 ('docker-top',): json.dumps({'processes': app()['processes']}),
                 ('pct', 'exec'): 'drwxr-xr-x|755|1000|1000|alice|alice|directory|/srv/app\n'})
    monkeypatch.setattr(ssh, 'run', p)
    d = docker.collect('h', 22, 9006, scan.STAT, 10)
    assert [a['name'] for a in d['apps']] == ['paperless', 'redis']
    assert d['apps'][0]['processes'][1]['comm'] == 'gunicorn' and 'processes' not in d['apps'][1]  # gestoppt: kein top
    assert d['stat']['/srv/app']['uid'] == 1000
    stat_call = next(c for c in p.calls if c[:2] == ['pct', 'exec'])
    assert '/srv' in stat_call and '/srv/app' in stat_call and '/var/lib/docker/volumes/cfg/_data' in stat_call


def test_scan_nur_ab_waechter_8(monkeypatch):
    p = Proxmox({('getent',): '', ('findmnt',): '{"filesystems": []}'})
    monkeypatch.setattr(ssh, 'run', p)
    g = {'vmid': 9006, 'config': {'mounts': []}}
    scan._details('h', 22, g, guard=7)
    assert not any(c[0] == 'docker-ps' for c in p.calls)
    scan._details('h', 22, g, guard=8)
    assert any(c == ['docker-ps', '9006'] for c in p.calls)


# ---------------------------------------------------------------- Anzeige und Rechnung
def test_docker_apps_kette():
    g = guest([app()])
    v = view.docker_apps({'host_info': {'passwd': []}}, g)
    a = v['apps'][0]
    assert (a['writer']['uid'], a['ct_name'], a['host_uid']) == (1000, 'alice', 101000)
    data = next(f for f in a['folders'] if f['destination'] == '/data')
    assert data['res']['read'] and data['res']['write']
    cfg = next(f for f in a['folders'] if f['destination'] == '/config')
    assert cfg['volume'] and cfg['res']['read'] and not cfg['res']['write']           # gehört root, App ist 1000


def test_ordner_davor_zaehlen_fuer_die_app_nicht():
    """/var/lib/docker ist 710 root: der LXC-Benutzer 1000 käme nicht hinein, die App bekommt das Volume aber direkt."""
    closed = {**DIR, 'mode': 'drwx--x---', 'octal': '710'}
    g = guest([app()], stat={'/var/lib/docker': closed})
    a = view.docker_apps({}, g)['apps'][0]
    assert next(f for f in a['folders'] if f['destination'] == '/config')['res']['read']
    assert not view.diagnose(g, 1000, '/var/lib/docker/volumes/cfg/_data')['read']   # alice im LXC: nein


def test_docker_apps_ohne_docker():
    g = guest([])
    del g['details']['docker']
    assert view.docker_apps({}, g) is None


def test_befund_kann_nicht_schreiben():
    g = guest([app(env={'PUID': '1001', 'PGID': '1001'}, processes=None)])
    found = findings.docker_findings(g)
    f = next(f for f in found if f['key'] == 'docker-schreiben')
    assert f['level'] == 'problem' and f['source'] == '/srv/app'
    assert f['extra'][1] == 'PUID'
    assert f['advice'][0]['link'] == '/diagnose?ct=9006&app=paperless&path=/srv/app'


def test_befund_schreibt_als_root():
    g = guest([app(processes=[{'uid': 0, 'gid': 0, 'comm': 'nginx'}])], stat={'/srv/app': STAT_ROOT})
    keys = [f['key'] for f in findings.docker_findings(g)]
    assert 'docker-root' in keys and 'docker-schreiben' not in keys
    priv = guest([app(processes=[{'uid': 0, 'gid': 0, 'comm': 'nginx'}])], stat={'/srv/app': STAT_ROOT}, unprivileged=False)
    assert 'docker-root' not in [f['key'] for f in findings.docker_findings(priv)]


def test_befund_puid_wirkt_nicht():
    g = guest([app(env={'PUID': '1001'})])
    f = next(f for f in findings.docker_findings(g) if f['key'] == 'docker-puid')
    assert f['level'] == 'info' and 'PUID=1001' in f['text']


def test_volume_ist_kein_befund():
    keys = [f['key'] for f in findings.docker_findings(guest([app()]))]
    assert keys == []                                                                 # /config gehört root: Volume, kein Problem


# ---------------------------------------------------------------- Seiten
@pytest.fixture
def pve(client, monkeypatch):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_guard='8')
    g = guest([app(env={'PUID': '1000', 'PGID': '1000'}, processes=None)])
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [g], 'error': ''})
    monkeypatch.setattr(scan, 'start', lambda *a, **k: True)
    return g


def test_container_seite_reiter_docker(client, pve):
    r = client.get('/container/9006')
    assert '?tab=docker' in r.text
    r = client.get('/container/9006?tab=docker')
    assert 'paperless' in r.text and 'aus der Stack-Datei' in r.text and '101000' in r.text
    assert '/diagnose?ct=9006&amp;app=paperless&amp;path=/srv/app' in r.text


def test_ohne_docker_kein_reiter(client, pve):
    g = guest([])
    del g['details']['docker']
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [g], 'error': ''})
    assert '?tab=docker' not in client.get('/container/9006').text
    assert 'Docker-App' not in client.get('/container/9006?tab=docker').text      # fällt auf Überblick zurück


def test_pruefen_mit_app(client, pve):
    r = client.get('/diagnose?ct=9006&app=paperless&path=/srv/app')
    assert 'Docker-App paperless: schreibt als 1000:1000' in r.text
    assert 'value="app:paperless" selected' in r.text
    r2 = client.get('/diagnose?ct=9006&uid=app:paperless&path=/srv/app')             # aus der Auswahl
    assert 'Docker-App paperless' in r2.text


def test_pruefen_unbekannte_app(client, pve):
    r = client.get('/diagnose?ct=9006&app=gibtsnicht&path=/srv/app')
    assert r.status_code == 200 and 'Docker-App gibtsnicht' not in r.text


def test_empfehlungen_fuer_eine_app():
    g = guest([app(env={'PUID': '1001', 'PGID': '1001'}, processes=None)])
    u = view.app_user(g, g['details']['docker']['apps'][0])
    res = view.diagnose(g, None, '/srv/app', user=u)
    tips = findings.for_diagnose({}, g, u, '/srv/app', res)
    texts = [t['text'][0] for t in tips]
    assert texts[0].startswith('Der App eine Nummer geben') and tips[0]['text'][1] == 'PUID=1000 PGID=1000'
    assert not any('usermod' in (t['cmd'] or '') or 'g+w' in (t['cmd'] or '') for t in tips)  # App ist nicht in Gruppe 1000


def test_lange_volume_kennung_wird_gekuerzt(client, pve):
    """Anonyme Volumes haben 64 Hex-Zeichen im Pfad: gekürzt anzeigen, voll im Tooltip (Fehler aus Abnahme 1.1, B3)."""
    vol = '/var/lib/docker/volumes/b5db0401fface1b1e5c0d10aa6a4fff9f8b506721afddf9d3437deacb524e55b/_data'
    assert view.short_path(vol) == '/var/lib/docker/volumes/b5db0401…e55b/_data'
    assert view.short_path('/srv/app') == '/srv/app'
    g = guest([app(mounts=[{'type': 'volume', 'source': vol, 'destination': '/data/stacks', 'rw': True}])])
    scan.save({'started': '', 'finished': db.now(), 'host': '10.0.0.8', 'guests': [g], 'error': ''})
    r = client.get('/container/9006?tab=docker')
    assert f'title="{vol}"' in r.text and '>/var/lib/docker/volumes/b5db0401…e55b/_data' in r.text
