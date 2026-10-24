"""Mehrsprachigkeit (wie MediaDB): Deutsch ist die Quellsprache, Übersetzungen stehen in locales/<sprache>.json.

Schlüssel sind die deutschen Texte. Ein Platzhalter § steht für eingesetzte Werte (Zahlen, Namen).
Text zwischen *Sternchen* wird hervorgehoben (<em>). Fehlt eine Übersetzung, erscheint der deutsche Text."""
import json
import re
from pathlib import Path

from markupsafe import Markup, escape

LANGS = {'de': 'Deutsch', 'en': 'English'}
DEFAULT = 'de'
_DIR = Path(__file__).parent / 'locales'
_TABLES = {}
_EM = re.compile(r'\*([^*]+)\*')


def _load(lang):
    if lang not in _TABLES:
        f = _DIR / f'{lang}.json'
        try:
            _TABLES[lang] = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        except Exception:
            _TABLES[lang] = {}
    return _TABLES[lang]


def _text(lang, key):
    norm = ' '.join(str(key).split())
    if lang != DEFAULT and lang in LANGS:
        return _load(lang).get(norm, norm)
    return norm


def tr(lang, key, *args):
    """Text übersetzen und als sicheres HTML zurückgeben. Platzhalter § werden der Reihe nach gefüllt."""
    if key is None:
        return Markup('')
    text = _text(lang, key)
    parts = text.split('§')
    out = [escape(parts[0])]
    for i, p in enumerate(parts[1:]):
        out.append(escape(args[i]) if i < len(args) else '')
        out.append(escape(p))
    res = Markup('').join(out)
    return Markup(_EM.sub(r'<em>\1</em>', res)) if '*' in text else res


def tr_text(lang, key, *args):
    """Wie tr, aber als einfacher Text ohne HTML (für JavaScript-Texte und Titel)."""
    if key is None:
        return ''
    parts = _text(lang, key).replace('*', '').split('§')
    out = parts[0]
    for i, p in enumerate(parts[1:]):
        out += (str(args[i]) if i < len(args) else '') + p
    return out
