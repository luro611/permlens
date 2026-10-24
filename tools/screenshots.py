"""Macht die Bildschirmfotos für README und Anleitung neu (wie bei MediaDB):
docs/bilder/*.png auf Deutsch, docs/bilder/en/*.png auf Englisch, jeweils hell und dunkel (-dunkel.png).

Nur von der Test-Instanz für pve10 (Test-LXCs 9001–9006), nie von einem echten Proxmox: keine echten Daten in den
Bildern. Die Instanz muss laufen und pve10 eingelesen haben. Das Skript ändert nichts: Die Vorschau einer Änderung
wird nur angezeigt, nicht ausgeführt.

Voraussetzungen (einmalig, nur auf dem Mac, nicht im Image): Google Chrome und Playwright:
    .venv/bin/python -m pip install playwright
Aufruf im Projektordner (APP_PASSWORD wie beim Start der Test-Instanz):
    APP_PASSWORD=… .venv/bin/python tools/screenshots.py              alle Bilder
    APP_PASSWORD=… .venv/bin/python tools/screenshots.py pruefen      nur Bilder, deren Name so beginnt
Adresse der Instanz: PERMLENS_URL (Standard http://127.0.0.1:8011)."""
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'bilder'
BASE = os.environ.get('PERMLENS_URL', 'http://127.0.0.1:8011').rstrip('/')
W, H = 1200, 820
CSS = '*{transition:none!important;animation:none!important}.pl-insecure{display:none!important}'


def open_change(page):
    """Beim ersten eigenen Benutzer „Ändern …“ aufklappen."""
    page.locator('#benutzer ~ * details.pl-rowact').first.evaluate('d => d.open = true')


def preview(page):
    """„Neue Gruppe …“ ausfüllen und die Vorschau öffnen (nur Vorschau, nichts wird ausgeführt)."""
    form = page.locator('form:has(input[name=action][value=gruppe-anlegen])')
    form.locator('xpath=ancestor::details').evaluate('d => d.open = true')
    form.locator('input[name=name]').fill('medien')
    with page.expect_navigation():
        form.locator('button').click()


# Name, Adresse, was vorher zu tun ist, Höhe des Ausschnitts (None = ganze Seite)
SHOTS = [
    ('anmeldung', '/login', None, 1100),
    ('uebersicht', '/', None, 1250),
    ('probleme', '/probleme', None, 1000),
    ('pruefen', '/diagnose?ct=9002&uid=1000&path=/mnt/test', None, 1350),
    ('container-benutzer', '/container/9003?tab=benutzer', open_change, 1500),
    ('vorschau', '/container/9003?tab=benutzer', preview, 1450),
    ('aenderungen', '/aenderungen', None, 1000),
    ('mapping-umstieg', '/mapping?art=umstieg&ct=9001', None, 1500),
    ('container-host', '/container/9005?tab=host', None, 1300),
]


def login(browser, password):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(BASE + '/login')
    page.fill('input[name=password]', password)
    with page.expect_navigation():
        page.press('input[name=password]', 'Enter')
    if '/login' in page.url:
        sys.exit('Anmeldung fehlgeschlagen. Stimmt APP_PASSWORD? (Zwei-Faktor-Anmeldung muss auf der Test-Instanz aus sein.)')
    state = ctx.storage_state()
    ctx.close()
    return state


def shrink(path):
    """Metadaten weg, auf 256 Farben ohne Rastern (bei flachen Oberflächen nicht zu sehen, etwa ein Drittel der Größe),
    stärker komprimieren. Braucht ImageMagick, ohne bleibt das Bild, wie es ist."""
    try:
        subprocess.run(['magick', str(path), '-strip', '-dither', 'None', '-colors', '256',
                        '-define', 'png:compression-level=9', f'PNG8:{path}'], check=True)
    except (OSError, subprocess.CalledProcessError):
        pass


def main(only):
    password = os.environ.get('APP_PASSWORD') or sys.exit('APP_PASSWORD fehlt (Passwort der Test-Instanz).')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        state = login(browser, password)
        for lang, out, locale in (('de', OUT, 'de-DE'), ('en', OUT / 'en', 'en-GB')):
            out.mkdir(parents=True, exist_ok=True)
            for scheme, suffix in (('light', ''), ('dark', '-dunkel')):
                for name, url, before, height in SHOTS:
                    if only and not any(name.startswith(o) for o in only):
                        continue
                    ctx = browser.new_context(viewport={'width': W, 'height': H}, locale=locale, color_scheme=scheme,
                                              storage_state=None if name == 'anmeldung' else state)
                    ctx.add_cookies([{'name': 'permlens_lang', 'value': lang, 'url': BASE}])
                    page = ctx.new_page()
                    page.goto(BASE + url, wait_until='networkidle')
                    if before:
                        before(page)
                        page.wait_for_load_state('networkidle')
                    page.add_style_tag(content=CSS)
                    target = out / f'{name}{suffix}.png'
                    h = min(height, page.evaluate('document.documentElement.scrollHeight'))
                    page.screenshot(path=target, full_page=True, clip={'x': 0, 'y': 0, 'width': W, 'height': h})
                    shrink(target)
                    print(f'{target.relative_to(ROOT)}  ({target.stat().st_size // 1024} KB)')
                    ctx.close()
        browser.close()


if __name__ == '__main__':
    main(sys.argv[1:])
