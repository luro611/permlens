"""Hinweis „Neue Version verfügbar“ (AP 5.4, 0.5.7): GitHub wird nie wirklich gefragt, urlopen ist ersetzt."""
import io
import json
import urllib.error

import pytest

from app import config, db, updates


@pytest.fixture
def an(monkeypatch):
    """Update-Prüfung eingeschaltet, Zustand frisch, Version 0.5.7."""
    monkeypatch.delenv('UPDATE_CHECK', raising=False)
    monkeypatch.setattr(config, 'version', lambda: '0.5.7')
    db.set_settings(update_check='1')
    updates.STATE.update(latest=None, url=None, checked=0.0, error='')
    yield
    updates.STATE.update(latest=None, url=None, checked=0.0, error='')


def antwort(monkeypatch, body=None, code=None, fehler=None):
    seen = {}

    def urlopen(req, timeout=10):
        seen['url'], seen['ua'] = req.full_url, req.get_header('User-agent')
        if fehler:
            raise fehler
        if code:
            raise urllib.error.HTTPError(req.full_url, code, 'x', {}, None)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(updates.urllib.request, 'urlopen', urlopen)
    return seen


def test_versionen_vergleichen():
    assert updates.parse('v1.0.2') == (1, 0, 2) and updates.parse('0.6') == (0, 6, 0)
    assert updates.parse('v1.0.0-rc1') is None and updates.parse('') is None


def test_neuere_version(an, monkeypatch):
    seen = antwort(monkeypatch, {'tag_name': 'v1.0.0', 'html_url': 'https://github.com/luro611/permlens/releases/tag/v1.0.0'})
    assert updates.check()[0] == '1.0.0'
    assert seen['url'] == 'https://api.github.com/repos/luro611/permlens/releases/latest'
    assert seen['ua'].startswith('PermLens/0.5.7')
    assert updates.info() == {'version': '1.0.0', 'url': 'https://github.com/luro611/permlens/releases/tag/v1.0.0'}


def test_gleiche_oder_aeltere_version(an, monkeypatch):
    antwort(monkeypatch, {'tag_name': 'v0.5.7'})
    updates.check()
    assert updates.info() is None


def test_vorabversion_zaehlt_nicht(an, monkeypatch):
    antwort(monkeypatch, {'tag_name': 'v2.0.0', 'prerelease': True})
    assert updates.check() == (None, None) and updates.info() is None


def test_privates_repository_still(an, monkeypatch):
    antwort(monkeypatch, code=404)
    assert updates.check() == (None, None)
    assert updates.STATE['error'] == '' and updates.STATE['checked'] > 0


def test_kein_internet(an, monkeypatch):
    antwort(monkeypatch, fehler=OSError('Name or service not known'))
    assert updates.check() == (None, None) and updates.STATE['error']


def test_abschalten(an, monkeypatch):
    antwort(monkeypatch, {'tag_name': 'v1.0.0'})
    updates.check()
    db.set_settings(update_check='0')
    assert not updates.enabled() and updates.info() is None
    db.set_settings(update_check='1')
    monkeypatch.setenv('UPDATE_CHECK', '0')  # Stack-Datei geht vor
    assert updates.env_off() and not updates.enabled() and updates.info() is None


def test_fusszeile_und_einstellungen(an, client, monkeypatch):
    antwort(monkeypatch, {'tag_name': 'v1.0.0', 'html_url': 'https://github.com/luro611/permlens/releases/tag/v1.0.0'})
    r = client.post('/settings/updates/check', follow_redirects=False)
    assert r.status_code == 303 and 'message=' in r.headers['location']
    r = client.get('/settings')
    assert 'Neue Version 1.0.0 verfügbar' in r.text and 'class="updnote"' in r.text and 'Jetzt nachsehen' in r.text
    client.post('/settings/updates', data={})  # Häkchen weg
    assert db.get_setting('update_check') == '0'
    r = client.get('/settings')
    assert 'class="updnote"' not in r.text and 'Jetzt nachsehen' not in r.text
    client.post('/settings/updates', data={'on': '1'})
    assert db.get_setting('update_check') == '1'
    monkeypatch.setenv('UPDATE_CHECK', '0')
    r = client.get('/settings')
    assert 'UPDATE_CHECK=0' in r.text and 'name="on"' not in r.text
