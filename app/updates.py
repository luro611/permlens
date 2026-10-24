"""Hinweis auf eine neue Version (wie MediaDB): alle sechs Stunden das neueste Release auf GitHub abfragen.

Gelesen wird nur die öffentliche Release-Liste von luro611/permlens. PermLens schickt dabei nichts mit außer der
eigenen Versionsnummer im User-Agent, keine Daten vom Proxmox. Abschaltbar in den Einstellungen und mit UPDATE_CHECK=0
in der Stack-Datei (dann ganz aus, auch in den Einstellungen nicht einschaltbar).

Ein Release legt tools/publish.sh erst an, wenn das Image hochgeladen ist. Der Hinweis erscheint also erst, wenn
„Pull“ in Dockhand die neue Version auch wirklich bringt. Solange das Repository privat ist, antwortet GitHub mit 404,
dann zeigt PermLens still nichts an."""
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import config, db

REPO = 'luro611/permlens'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASES = f'https://github.com/{REPO}/releases'
EVERY = 6 * 3600
STATE = {'latest': None, 'url': None, 'checked': 0.0, 'error': ''}


def parse(v):
    """'v1.0.2' → (1, 0, 2); Unlesbares → None."""
    m = re.fullmatch(r'v?(\d+)\.(\d+)(?:\.(\d+))?', str(v or '').strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def env_off():
    """UPDATE_CHECK=0 (oder false, no, nein, off) in der Stack-Datei."""
    return os.environ.get('UPDATE_CHECK', '').strip().lower() in ('0', 'false', 'no', 'nein', 'off')


def enabled():
    return not env_off() and db.get_setting('update_check', '1') != '0'


def check():
    """Neuestes Release holen. Gibt (version, url) zurück oder (None, None)."""
    req = urllib.request.Request(API, headers={'User-Agent': f'PermLens/{config.version()} (+https://github.com/{REPO})',
                                               'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode('utf-8'))
        tag = d.get('tag_name') or ''
        if d.get('draft') or d.get('prerelease') or not parse(tag):
            STATE.update(checked=time.time(), error='')
            return None, None
        STATE.update(latest=tag.lstrip('v'), url=d.get('html_url') or RELEASES, checked=time.time(), error='')
    except urllib.error.HTTPError as e:
        if e.code == 404:  # noch kein Release oder Repository privat: still nichts anzeigen
            STATE.update(latest=None, url=None, checked=time.time(), error='')
            return None, None
        STATE.update(checked=time.time(), error=f'GitHub antwortet mit {e.code}.')
        logging.info('Update-Prüfung nicht möglich: %s', e)
    except Exception as e:  # kein Internet, DNS, Zeitüberschreitung
        STATE.update(checked=time.time(), error=str(e)[:200])
        logging.info('Update-Prüfung nicht möglich: %s', e)
    return STATE['latest'], STATE['url']


def info():
    """Für die Fußzeile: {'version', 'url'}, wenn ein neueres Release vorliegt, sonst None."""
    if not STATE['latest'] or not enabled():
        return None
    now, new = parse(config.version()), parse(STATE['latest'])
    if now and new and new > now:
        return {'version': STATE['latest'], 'url': STATE['url'] or RELEASES}
    return None


def scheduler():
    """Kurz nach dem Start und danach alle EVERY Sekunden prüfen."""
    def loop():
        time.sleep(30)
        while True:
            try:
                if enabled():
                    check()
            except Exception:
                logging.exception('Update-Prüfung')
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True, name='update-check').start()
