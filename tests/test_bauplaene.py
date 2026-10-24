"""AP 6.6: gespeicherte Baupläne im Mapping-Assistenten und Vorschlag aus einer Docker-App (Rest von AP 6.2)."""
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import pytest

from app import db
from app.pve import bauplan, scan
from conftest import set_pve  # noqa: E402
from test_bauplan import SCAN, ST

APP = {'name': 'paperless', 'image': 'paperless', 'state': 'running', 'user': '', 'env': {'USERMAP_UID': '1000'},
       'mounts': [{'type': 'bind', 'source': '/mnt/share/paperless/data', 'destination': '/data', 'rw': True},
                  {'type': 'bind', 'source': '/mnt/share/paperless/media', 'destination': '/media', 'rw': True},
                  {'type': 'bind', 'source': '/mnt/ro/archiv', 'destination': '/archiv', 'rw': False},
                  {'type': 'volume', 'source': '/var/lib/docker/volumes/cfg/_data', 'destination': '/config', 'rw': True},
                  {'type': 'bind', 'source': '/opt/paperless/tmp', 'destination': '/tmp', 'rw': True}],
       'processes': [{'uid': 0, 'gid': 0, 'comm': 's6'}, {'uid': 1000, 'gid': 1000, 'comm': 'gunicorn'}]}
DOCKER = {'vmid': 9006, 'name': 'docker', 'type': 'lxc', 'status': 'running',
          'config': {'unprivileged': True, 'mounts': [
              {'key': 'mp0', 'kind': 'bind', 'source': '/srv/share', 'target': '/mnt/share', 'host_stat': ST},
              {'key': 'mp1', 'kind': 'bind', 'source': '/srv/archiv', 'target': '/mnt/ro', 'host_stat': ST}]},
          'details': {'docker': {'apps': [APP], 'error': '', 'more': 0}}}
SCAN_D = {**SCAN, 'guests': SCAN['guests'] + [DOCKER]}


@pytest.fixture
def pve(client):
    set_pve(pve_host='10.0.0.8', pve_port='22', pve_connected='1', pve_guard='8')
    with closing(db.connect()) as c, c:
        c.execute('DELETE FROM plans')
    scan.save({**SCAN_D, 'started': '', 'finished': db.now(), 'error': ''})
    return client


def query(r):
    return {k: v[0] for k, v in parse_qs(urlsplit(r.headers['location']).query).items()}


# ---------------------------------------------------------------- was gespeichert wird
def test_gespeichert_ohne_nummer_und_luecken():
    p = bauplan.stored({'vmid': '160', 'app': 'docker', 'uid': ' 1000 ', 'gid': '1000', 'gids': '',
                        'src0': '', 'src1': '/srv/share', 'dst1': '/data', 'ro1': '1', 'src2': '/srv/b', 'fremd': 'x'})
    assert p == {'app': 'docker', 'uid': '1000', 'gid': '1000', 'src0': '/srv/share', 'dst0': '/data', 'ro0': '1',
                 'src1': '/srv/b'}
    s = bauplan.summary(p)
    assert s['folders'] == ['/srv/share → /data (ro)', '/srv/b'] and s['ids'] == '1000:1000'
    assert bauplan.summary({'src0': '/x'})['ids'] == '' and bauplan.clean_name('  a   b ') == 'a b'


def test_je_proxmox_und_gleicher_name_ersetzt(client):
    pid, ersetzt = db.save_plan(901, 'paperless', {'src0': '/a'})
    assert not ersetzt
    assert db.save_plan(901, 'paperless', {'src0': '/b'}) == (pid, True)
    db.save_plan(902, 'paperless', {'src0': '/c'})
    assert [p['params'] for p in db.plans(901)] == [{'src0': '/b'}]
    assert db.plan(pid, 902) is None  # Bauplan eines anderen Proxmox
    db.rename_plan(pid, 902, 'fremd')
    db.delete_plan(pid, 902)
    assert db.plan(pid, 901)['name'] == 'paperless'
    db.delete_plan(pid, 901)
    assert db.plans(901) == []


# ---------------------------------------------------------------- Oberfläche
def test_speichern_laden_umbenennen_loeschen(pve):
    r = pve.get('/mapping')
    assert 'Gespeicherte Baupläne' in r.text and 'Noch keine' in r.text
    r = pve.post('/mapping/plaene', data={'name': 'paperless mit /srv/share', 'vmid': '160', 'app': 'paperless',
                                          'src0': '/srv/share', 'dst0': '/data'}, follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'].endswith('#plaene')
    q = query(r)
    assert q['src0'] == '/srv/share' and 'vmid' not in q and 'gespeichert' in q['message']
    pid = int(q['geladen'])
    r = pve.get(r.headers['location'])
    assert 'paperless mit /srv/share' in r.text and '/srv/share → /data' in r.text and 'Schritt für Schritt' in r.text
    assert f'/mapping/plaene/{pid}' in r.text and 'value="paperless mit /srv/share"' in r.text

    r = pve.get(f'/mapping/plaene/{pid}', follow_redirects=False)
    assert query(r) == {'app': 'paperless', 'src0': '/srv/share', 'dst0': '/data', 'geladen': str(pid)}
    assert 'Geladen: Bauplan' in pve.get(r.headers['location']).text

    db.save_plan((db.active_host() or {})['id'], 'anderer', {'src0': '/srv/share'})
    r = pve.post(f'/mapping/plaene/{pid}/umbenennen', data={'name': 'anderer'})
    assert 'gibt es schon' in r.text
    r = pve.post(f'/mapping/plaene/{pid}/umbenennen', data={'name': '  paperless   neu '})
    assert 'heißt jetzt „paperless neu“' in r.text and db.plan(pid, db.active_host()['id'])['name'] == 'paperless neu'
    r = pve.post(f'/mapping/plaene/{pid}/loeschen')
    assert 'gelöscht' in r.text and db.plan(pid, db.active_host()['id']) is None
    assert 'gibt es nicht' in pve.get(f'/mapping/plaene/{pid}').text
    assert [e['result'] for e in db.audit_entries(10) if e['action'] == 'bauplan'][:3] == ['geloescht', 'umbenannt', 'gespeichert']


@pytest.mark.parametrize('data', [
    {'name': '', 'src0': '/srv/share'},             # ohne Namen
    {'name': 'kaputt', 'src0': 'relativ'},          # Bauplan mit Fehlern
])
def test_speichern_abgelehnt(pve, data):
    r = pve.post('/mapping/plaene', data=data, follow_redirects=False)
    assert 'Bitte einen Namen' in query(r)['message'] and db.plans(db.active_host()['id']) == []


def test_speichern_nur_von_permlens(pve):
    pve.post('/mapping/plaene', data={'name': 'x', 'src0': '/srv/share'}, headers={'origin': 'http://boese.example'})
    assert db.plans(db.active_host()['id']) == []


def test_englisch(pve):
    pve.cookies.set('permlens_lang', 'en')
    r = pve.post('/mapping/plaene', data={'name': 'p', 'src0': '/srv/share'})
    assert 'Saved blueprints' in r.text and 'Blueprint “p” saved.' in r.text and 'Save blueprint' in r.text
    pve.cookies.delete('permlens_lang')


# ---------------------------------------------------------------- Vorschlag aus einer Docker-App
def test_vorschlag_aus_app():
    params, notes = bauplan.from_app(DOCKER, APP)
    # beide App-Ordner liegen im selben Mount des LXC: der Host-Ordner kommt einmal in den Bauplan, am selben Ziel
    assert params == {'app': 'paperless', 'uid': '1000', 'gid': '1000', 'src0': '/srv/share', 'dst0': '/mnt/share',
                      'src1': '/srv/archiv', 'dst1': '/mnt/ro', 'ro1': '1'}
    texts = ' '.join(n[0] for n in notes)
    assert 'Docker-Volume' in texts and 'Dateisystem des LXC' in texts
    p = bauplan.make(SCAN_D, params)
    assert not p['errors'] and p['env'] == ['USERMAP_UID=1000', 'USERMAP_GID=1000']


def test_vorschlag_root_und_ohne_ordner():
    params, notes = bauplan.from_app(DOCKER, {**APP, 'env': {}, 'processes': [{'uid': 0, 'gid': 0, 'comm': 'x'}], 'mounts': []})
    assert params == {'app': 'docker'}
    assert 'schreibt als root' in notes[0][0] and 'keinen Ordner vom Host' in notes[-1][0]


def test_link_im_docker_reiter(pve):
    r = pve.get('/container/9006?tab=docker')
    assert '/mapping/aus-app?ct=9006&amp;app=paperless' in r.text
    r = pve.get('/mapping/aus-app?ct=9006&app=paperless', follow_redirects=False)
    q = query(r)
    assert q['src0'] == '/srv/share' and q['uid'] == '1000' and q['aus'] == '9006:paperless'
    r = pve.get(r.headers['location'])
    assert 'Vorbelegt aus Docker' in r.text and 'Docker-Volume' in r.text and 'value="paperless"' in r.text
    assert 'USERMAP_UID=1000' in r.text
    assert pve.get('/mapping/aus-app?ct=9006&app=gibtsnicht', follow_redirects=False).headers['location'] == '/mapping'
