"""PermLens – Rechte-Manager für LXC-Container. Start der Web-App (FastAPI)."""
import hashlib
import ipaddress
import json
import re
import time
from datetime import datetime
from functools import partial
from urllib.parse import quote, urlencode, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db, i18n, setup, tls, totp, updates
from . import security as sec
from .pve import access, bauplan, change, console, docker, explain, findings, hostchange, scan, ssh, view

config.init()
db.init()
GUARD_FILE = config.BASE / 'host' / 'permlens-guard'

LANG_COOKIE = 'permlens_lang'
HOST_COOKIE = 'permlens_host'  # gewählter Proxmox, gilt pro Browser
FIVE_YEARS = 60 * 60 * 24 * 365 * 5

SEC = sec.Settings(config.DATA)
app = FastAPI(title='PermLens', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(sec.Gate, settings=SEC)
app.mount('/static', StaticFiles(directory=str(config.BASE / 'static')), name='static')
templates = Jinja2Templates(directory=str(config.BASE / 'app' / 'templates'))


@app.middleware('http')
async def drop_empty_query(request: Request, call_next):
    """Leere Felder in der Adresse (z. B. ct= bei einer leeren Auswahl) so behandeln, als fehlten sie.
    Sonst lehnt FastAPI die Seite mit einer rohen Fehlermeldung ab, weil '' keine Zahl ist."""
    qs = request.scope.get('query_string', b'')
    if qs:
        pairs = [p for p in qs.split(b'&') if p and not p.endswith(b'=')]
        request.scope['query_string'] = b'&'.join(pairs)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def invalid_input(request: Request, exc):
    """Ungültige Werte in Adresse oder Formular: verständliche Seite statt JSON (z. B. /container/abc)."""
    return templates.TemplateResponse(request, 'fehler.html', ctx(request, area=''), status_code=400)


@app.middleware('http')
async def active_host(request: Request, call_next):
    """Gewählten Proxmox aus dem Cookie für diese Anfrage merken (db.ACTIVE). Gilt auch in den Routen,
    die FastAPI in einem eigenen Thread ausführt (der Kontext wird mitgegeben)."""
    hid = request.cookies.get(HOST_COOKIE, '')
    token = db.ACTIVE.set(int(hid) if hid.isdigit() else None)
    try:
        return await call_next(request)
    finally:
        db.ACTIVE.reset(token)
templates.env.globals['app_version'] = config.version()
templates.env.globals['asset_v'] = max(int((config.BASE / 'static' / f).stat().st_mtime)
                                       for f in ('style.css', 'permlens.css'))


def get_lang(request):
    lang = request.cookies.get(LANG_COOKIE, i18n.DEFAULT)
    return lang if lang in i18n.LANGS else i18n.DEFAULT


def ctx(request, **kw):
    """Werte, die jede Seite braucht."""
    lang = get_lang(request)
    return {'request': request, 'lang': lang, 'langs': i18n.LANGS, 'base': '',
            'insecure': request.url.scheme == 'http' and tls.enabled(),
            'hosts': db.hosts(), 'active': db.active_host(),
            '_': partial(i18n.tr, lang), '_t': partial(i18n.tr_text, lang), **kw}


def safe_next(nxt):
    """Nur Ziele innerhalb der App zulassen (keine fremden Adressen)."""
    return nxt if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt else '/'


def local_time(iso):
    """UTC-Zeitstempel aus der Datenbank in Ortszeit (TZ des Containers), z. B. '17.10.2026 14:52'."""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime('%d.%m.%Y %H:%M')
    except (TypeError, ValueError):
        return ''


templates.env.filters['local_time'] = local_time
templates.env.tests['match_mp'] = lambda key: bool(hostchange.MP_KEY.match(str(key or '')))
templates.env.globals['guard_new'] = re.search(r"^VERSION = '(\d+)'", GUARD_FILE.read_text(encoding='utf-8'), re.M).group(1)
templates.env.globals['update_info'] = updates.info  # Hinweis „Neue Version verfügbar“ in der Fußzeile
updates.scheduler()


@app.get('/', response_class=HTMLResponse)
def home(request: Request, message: str = ''):
    last = scan.latest()
    found = findings.collect(last)
    guests = (last or {}).get('guests', [])
    lxcs = [g for g in guests if g['type'] == 'lxc']
    s = pve_settings()
    extra = {} if s['connected'] else setup_ctx(request)
    return templates.TemplateResponse(request, 'home.html', ctx(
        request, area='home', host=s['host'], connected=s['connected'], last=last, message=message,
        scanning=scan.running(), scan_failed=scan.failed_since((last or {}).get('finished')), **extra,
        lxcs=lxcs, vms=[g for g in guests if g['type'] == 'qemu'],
        status=scan.status, mapping=scan.mapping, accounts=view.accounts, fcounts=findings.counts(found),
        top=[f for f in found if f['level'] == 'problem'][:3],
        counts={k: sum(1 for g in lxcs if scan.status(g) == k) for k in ('ok', 'aus', 'fehler')}))


@app.get('/container/{vmid}', response_class=HTMLResponse)
def container_page(request: Request, vmid: int, tab: str = 'ueberblick'):
    last = scan.latest()
    guest = view.find(last, vmid)
    if not guest:
        return RedirectResponse('/', 303)
    tab = {'mapping': 'ueberblick', 'mounts': 'ordner', 'freigaben': 'ordner'}.get(tab, tab)  # alte Adressen
    dk = view.docker_apps(last, guest)
    tab = tab if tab in ('ueberblick', 'benutzer', 'ordner', 'host') or (tab == 'docker' and dk) else 'ueberblick'
    own_groups = [x for x in ((guest.get('details') or {}).get('groups') or [])
                  if change.MIN_ID <= x['gid'] <= change.MAX_ID]
    return templates.TemplateResponse(request, 'container.html', ctx(
        request, area='home', last=last, tab=tab, v=view.container(last, guest),
        found=[f for f in findings.collect(last) if f['vmid'] == vmid],
        write_ok=change.write_allowed(pve_settings()['write'], vmid), free_gid=change.free_gid(guest, 2000),
        free_uid=change.free_uid(guest, 1000),
        mount_paths=sorted(t for t in change.targets(guest) if t != '/home'),
        own_users=[x for x in ((guest.get('details') or {}).get('users') or [])
                   if change.MIN_ID <= x['uid'] <= change.MAX_ID],
        guard_now=pve_settings()['guard'], own_groups=own_groups,
        own_group_names=[x['name'] for x in own_groups], conf=explain.conf(guest.get('config')), dk=dk,
        hc=host_change(last, vmid), known=bauplan.known_folders(last)))


def host_change(last, vmid):
    """Darf PermLens bei diesem Container am Host ändern (ab Wächter 9)? Stand des letzten Einlesens;
    vor dem Ausführen fragt PermLens den Wächter noch einmal frisch."""
    guard = pve_settings()['guard']
    info = (last or {}).get('host_change') or {}
    return {'guard_ok': hostchange.guard_ok(guard), 'guard_min': hostchange.GUARD_MIN,
            'allowed': hostchange.guard_ok(guard) and change.write_allowed(info.get('ids', ''), vmid),
            'ids': info.get('ids', ''), 'paths': info.get('paths', [])}


CAUSES = {
    '': 'Ja. Die Rechte erlauben Lesen und Schreiben.',
    'nobody': 'Der Ordner gehört für diesen Container nobody: Sein Besitzer auf dem Host ist hier nicht abgebildet. Dann gelten nur die Rechte für „andere“, auch für root.',
    'weg': 'Ein Ordner auf dem Weg dorthin lässt den Benutzer nicht hinein (x fehlt).',
    'rechte': 'Die Rechte erlauben es diesem Benutzer nicht.',
    'nur-lesen': 'Der Ordner ist nur zum Lesen eingehängt.',
    'fehlt': 'Diesen Pfad gibt es im Container nicht.',
    'offline': 'Der Ordner antwortet nicht.',
}


@app.get('/diagnose', response_class=HTMLResponse)
def diagnose_page(request: Request, ct: int = 0, uid: str = '', path: str = '', probe: int = 0, app: str = ''):
    """„Kann Benutzer X auf Pfad Y?“ Auswahl über GET, damit man Ergebnisse verlinken kann.
    app (oder uid=app:NAME aus der Auswahl): statt eines Benutzers eine Docker-App im Container (AP 6.2)."""
    if uid.startswith('app:'):
        app, uid = uid[4:], ''
    return render_diagnose(request, ct, int(uid) if uid.isdigit() else None, path, probe, app=app)


@app.post('/diagnose/schreibtest', response_class=HTMLResponse)
def diagnose_write_test(request: Request, ct: int = Form(0), uid: int = Form(0), path: str = Form(''),
                        app: str = Form('')):
    """Echter Schreibtest (Phase 3): legt als dieser Benutzer eine leere Testdatei an und löscht sie wieder."""
    if not same_origin(request):
        return RedirectResponse('/diagnose', 303)
    return render_diagnose(request, ct, uid, path, 0, write_test=True, app=app)


def render_diagnose(request, ct, uid, path, probe, write_test=False, app=''):
    last = scan.latest()
    lxcs = [g for g in (last or {}).get('guests', []) if g['type'] == 'lxc']
    guest = view.find(last, ct) if ct else None
    form, res, err, live = None, None, '', None
    path = path.strip().rstrip('/') or ('/' if path.strip() == '/' else '')
    app_user = None
    if guest:
        form = view.diagnose_form(guest)
        a = docker.find_app(guest, app) if app else None
        app_user = view.app_user(guest, a) if a else None
        if app_user:  # Docker-App: ihre Nummern, als Vorschlag ihre eingehängten Ordner
            uid = app_user['uid']
            form['paths'] = [m['source'] for m in docker.binds(a)] + [p for p in form['paths']
                                                                     if p not in {m['source'] for m in docker.binds(a)}]
        else:
            app = ''
        if guest.get('details') and form['users']:
            if not app_user and (uid is None or not any(u['uid'] == uid for u in form['users'] + form['system'])):
                uid = next((u['uid'] for u in form['users'] if u['uid'] != 0), form['users'][0]['uid'])
            path = path or (form['paths'][0] if form['paths'] else '')
            if path and not scan.valid_path(path):
                err, path = 'Der Pfad ist ungültig. Erlaubt sind absolute Pfade ohne Sonderzeichen.', path
            elif path:
                known = (guest.get('details') or {}).get('stat') or {}
                if path not in known and guest.get('status') == 'running':
                    s = pve_settings()
                    live, r = scan.stat_live(s['host'], s['port'], ct, path)
                    if r.rc == 124:
                        err = 'Der Ordner antwortet nicht. Ist das NAS ausgeschaltet?'
                ro = bool(app_user) and any(m['source'] == path and not m.get('rw', True)
                                            for m in docker.binds(docker.find_app(guest, app)))
                res = view.diagnose(guest, uid, path, live, user=app_user, readonly=ro)
    user = app_user or next((u for u in (form or {}).get('users', []) + (form or {}).get('system', [])
                             if u['uid'] == uid), None)
    tips = findings.for_diagnose(last, guest, user, path, res) if res and user else []
    guard = pve_settings()['guard']
    can_probe = bool(res and user and guest.get('status') == 'running' and guard.isdigit() and int(guard) >= 3
                     and res['cause'] not in ('fehlt', 'offline')
                     # Docker-Volume: die Gegenprobe ginge durch /var/lib/docker, das die App selbst nie betritt
                     and not (app_user and path.startswith('/var/lib/docker/')))
    check = None
    if probe and can_probe:
        s = pve_settings()
        gids = user['gids'] if app_user else [g['gid'] for g in (guest.get('details') or {}).get('groups', [])
                                              if user['name'] in g['members']]
        check = scan.probe(s['host'], s['port'], ct, user['uid'], user['gid'], gids, path)
        stat = ((guest.get('details') or {}).get('stat') or {}).get(path) or {}
        folder = 'directory' in (stat.get('type') or 'directory')
        if not check['error']:
            check['read'] = check['r'] and (check['x'] or not folder)
            check['write'] = check['w'] and (check['x'] or not folder)
            check['differs'] = check['read'] != res['read'] or check['write'] != res['write']
        db.audit('gegenprobe', target=f'{ct}:{path}', result='fehler' if check['error'] else 'ok',
                 client=client_of(request), uid=user['uid'])
    s = pve_settings()
    write_ok = bool(guest) and change.write_allowed(s['write'], ct)
    for t in tips:
        t['can_run'] = bool(t.get('act') and write_ok and guest.get('status') == 'running'
                            and ('path' not in t['act'] or change.path_ok(guest, t['act']['path'])))
    can_change = bool(res and write_ok and guest.get('status') == 'running' and change.path_ok(guest, path)
                      and res['cause'] not in ('fehlt', 'offline'))
    stat_now = {**(((guest or {}).get('details') or {}).get('stat') or {}), **(live or {})}.get(path) or {}
    wtest = None
    if write_test and can_change and user and access.is_dir(stat_now or {'type': 'directory'}):
        gids = user['gids'] if app_user else [g['gid'] for g in (guest.get('details') or {}).get('groups', [])
                                              if user['name'] in g['members']]
        wtest = change.write_test(s['host'], s['port'], ct, user, gids, path)
        db.audit('schreibtest', target=f'{ct}:{path}', client=client_of(request), uid=user['uid'],
                 result='fehler' if wtest['error'] else ('ja' if wtest['ok'] else 'nein'))
    found = findings.collect(last)
    return templates.TemplateResponse(request, 'diagnose.html', ctx(
        request, area='diagnose', last=last, lxcs=lxcs, guest=guest, form=form, ct=ct, uid=uid, path=path,
        res=res, err=err, causes=CAUSES, tips=tips, app=app, app_user=app_user, found=found, fcounts=findings.counts(found),
        can_probe=can_probe, check=check, can_change=can_change, write_ok=write_ok, wtest=wtest, user=user,
        stat_now=stat_now, mode_text=change.mode_text, guard_now=s['guard'],
        probe_nfs=bool(guest and (view.mount_for(guest.get('config') or {}, path) or {}).get('fs_kind') == 'nfs'),
        guard_old=bool(res and guard.isdigit() and int(guard) < 3)))


@app.get('/ordner/nummern', response_class=HTMLResponse)
def people_page(request: Request):
    last = scan.latest()
    return templates.TemplateResponse(request, 'people.html', ctx(
        request, area='ordner', otab='nummern', last=last, v=view.people(last)))


@app.get('/ordner/host', response_class=HTMLResponse)
def host_page(request: Request):
    last = scan.latest()
    return templates.TemplateResponse(request, 'host.html', ctx(
        request, area='ordner', otab='host', last=last, v=view.host(last), content_labels=view.CONTENT))


@app.get('/ordner', response_class=HTMLResponse)
def storage_page(request: Request):
    last = scan.latest()
    return templates.TemplateResponse(request, 'storage.html', ctx(
        request, area='ordner', otab='ordner', last=last, host=pve_settings()['host'], v=view.storage(last),
        found=findings.collect(last)))


# Alte Adressen (bis 0.4.0) leiten auf die neue Ordnung weiter (Usability-Runde, 0.4.1)
@app.get('/speicher')
def old_storage():
    return RedirectResponse('/ordner', 301)


@app.get('/host')
def old_host():
    return RedirectResponse('/ordner/host', 301)


@app.get('/benutzer')
def old_people():
    return RedirectResponse('/ordner/nummern', 301)


@app.get('/probleme', response_class=HTMLResponse)
def problems_page(request: Request):
    last = scan.latest()
    found = findings.collect(last)
    return templates.TemplateResponse(request, 'probleme.html', ctx(
        request, area='problems', last=last, found=found, fcounts=findings.counts(found)))


@app.post('/scan')
def run_scan(request: Request):
    s = pve_settings()
    if not s['host']:
        return RedirectResponse('/settings', 303)
    start_scan(s, client_of(request))
    return RedirectResponse('/', 303)


@app.get('/scan/status')
def scan_status():
    last = scan.latest()
    return {'running': scan.running(), 'finished': (last or {}).get('finished', '')}


def client_of(request):
    return request.client.host if request.client else ''


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request, next: str = '/'):
    return login_form(request, next)


def login_form(request, next, step='password', error='', status=200, **kw):
    return templates.TemplateResponse(request, 'login.html', ctx(
        request, area='login', next=safe_next(next), step=step, error=error,
        wait=SEC.locked_for(client_of(request)), **kw), status_code=status)


def signed_in(request, target, code_today=False):
    """Anmelde-Cookie setzen (auch nach dem Ein- oder Ausschalten der Zwei-Faktor-Anmeldung für diesen Browser).
    Ohne max_age: Das Cookie endet mit dem Browser, dann ist wieder das Passwort fällig. code_today: Der Code aus
    der App wurde gerade eingegeben, in diesem Browser bis 24:00 Uhr nicht noch einmal danach fragen."""
    r = RedirectResponse(target, 303) if isinstance(target, str) else target
    https = request.url.scheme == 'https'
    r.set_cookie(sec.COOKIE, SEC.make_token(until=SEC.session_until()), httponly=True, samesite='lax', secure=https)
    if code_today:
        until = sec.end_of_day()
        r.set_cookie(sec.DAY_COOKIE, SEC.make_day_token(), max_age=max(1, until - int(time.time())),
                     httponly=True, samesite='strict', secure=https)
    return r


@app.post('/login', response_class=HTMLResponse)
def login(request: Request, password: str = Form(''), next: str = Form('/')):
    client = client_of(request)
    if SEC.locked_for(client):
        db.audit('login', result='gesperrt', client=client)
        return login_form(request, next, status=429)
    if not SEC.password_ok(password):
        n = SEC.failed(client)
        db.audit('login', result='fehler', client=client, versuch=n)
        return login_form(request, next, error='falsch', left=max(0, sec.MAX_FAILS - n), status=401)
    if SEC.totp.active and SEC.day_ok(request.cookies.get(sec.DAY_COOKIE)):
        SEC.succeeded(client)  # Code heute in diesem Browser schon eingegeben
        db.audit('login', result='ok', client=client, zweiter_faktor='heute')
        return signed_in(request, safe_next(next))
    if SEC.totp.active:  # Passwort stimmt, jetzt noch der Code aus der App
        r = login_form(request, next, step='code')
        r.set_cookie(sec.STEP_COOKIE, SEC.make_step_token(), max_age=sec.STEP_AGE, httponly=True, samesite='strict',
                     secure=request.url.scheme == 'https')
        return r
    SEC.succeeded(client)
    db.audit('login', result='ok', client=client)
    return signed_in(request, safe_next(next))


@app.post('/login/code', response_class=HTMLResponse)
def login_code(request: Request, code: str = Form(''), next: str = Form('/')):
    client = client_of(request)
    if not SEC.step_ok(request.cookies.get(sec.STEP_COOKIE)):  # zu lange gewartet oder Passwort nie eingegeben
        return login_form(request, next, error='abgelaufen', status=401)
    if SEC.locked_for(client):
        db.audit('login', result='gesperrt', client=client, schritt='code')
        return login_form(request, next, step='code', status=429)
    kind = SEC.totp.check(code)
    if not kind:
        n = SEC.failed(client)
        db.audit('login', result='fehler', client=client, schritt='code', versuch=n)
        return login_form(request, next, step='code', error='code', left=max(0, sec.MAX_FAILS - n), status=401)
    SEC.succeeded(client)
    db.audit('login', result='ok', client=client, zweiter_faktor=kind)
    r = signed_in(request, safe_next(next), code_today=True)
    r.delete_cookie(sec.STEP_COOKIE)
    return r


@app.get('/logout')
def logout(request: Request):
    db.audit('logout', result='ok', client=client_of(request))
    r = RedirectResponse('/login', 303)
    r.delete_cookie(sec.COOKIE)
    r.delete_cookie(sec.DAY_COOKIE)  # Abmelden heißt: beim nächsten Mal wieder mit Code
    return r


# ---------------------------------------------------------------- Einstellungen: Verbindung zum Proxmox
def pve_settings(h=None):
    """Verbindung zum aktiven Proxmox dieser Anfrage (oder zum übergebenen Host aus db.hosts())."""
    h = h or db.active_host()
    if not h:  # noch kein Proxmox eingerichtet
        return {'id': None, 'name': '', 'host': '', 'port': '22', 'lxc_ip': db.get_setting('lxc_ip'), 'node': '',
                'guard': '', 'connected': False, 'write': ''}
    return {'id': h['id'], 'name': h['name'], 'host': h['host'], 'port': str(h['port']), 'lxc_ip': h['lxc_ip'],
            'node': h['node'], 'guard': h['guard'], 'connected': bool(h['connected']), 'write': h['write_ids']}


def origin_of(request):
    return f'{request.url.scheme}://{request.url.netloc}'


def setup_ctx(request):
    """Einrichtungs-Befehl für die Proxmox-Shell (Schlüssel wird bei Bedarf automatisch erzeugt)."""
    if not ssh.has_key():
        ssh.generate_key()
        db.audit('schluessel', result='neu', client=client_of(request))
    return {'setup_cmd': setup.command(origin_of(request), setup.token(), guard_sha256())}


def connect_and_scan(s, client=''):
    """Verbindung testen, bei Erfolg als verbunden merken und gleich neu einlesen.
    Gibt (Prüfungen, erste_verbindung) zurück: True, wenn vorher noch nichts von diesem Host eingelesen war."""
    steps = ssh.test_connection(s['host'], s['port'])
    ok = bool(steps) and all(x['ok'] for x in steps)
    if ok:  # ein Fehlschlag (z. B. Proxmox gerade aus) setzt die Einrichtung nicht zurück
        db.update_host(s['id'], connected=1, guard=steps[0].get('guard', ''), write_ids=steps[0].get('write_ids', ''))
    db.audit('verbindungstest', target=s['host'], result='ok' if ok else 'fehler', client=client,
             **({} if ok else {'grund': str(next((x['detail'] for x in steps if not x['ok']), ''))}))
    if ok:  # immer neu einlesen, sonst bleibt nach dem Test der alte Stand stehen (Lutz, 0.2.5)
        last = scan.latest(s['id'])
        start_scan(s, client)
        return steps, not last or last.get('host') != s['host']
    return steps, False


def start_scan(s, client=''):
    """Scan im Hintergrund, Ergebnis ins Protokoll."""
    def done(result):
        db.audit('scan', target=s['host'], result='fehler' if result['error'] else 'ok', client=client,
                 gaeste=len(result['guests']))
    return scan.start(s['host'], s['port'], done, s['id'])


def own_address(request):
    """Adresse, unter der PermLens im Browser geöffnet wurde, wenn es eine IP im Heimnetz ist (= Adresse des LXC)."""
    try:
        ip = ipaddress.ip_address(request.url.hostname or '')
    except ValueError:
        return ''
    return str(ip) if ip.is_private and not ip.is_loopback else ''


def settings_ctx(request, **kw):
    s = pve_settings()
    auto_ip = False
    if not s['lxc_ip'] and own_address(request):
        s['lxc_ip'] = own_address(request)  # automatisch erkannt und gleich gespeichert
        db.set_settings(lxc_ip=s['lxc_ip'])
        if s['id']:
            db.update_host(s['id'], lxc_ip=s['lxc_ip'])
        auto_ip = True
    origin = origin_of(request)
    values = {'message': '', 'err': '', 'steps': None, 'setup_cmd': '', **tfa_ctx(request), **kw}
    if not s['connected'] and not values['setup_cmd']:
        values.update(setup_ctx(request))
    return ctx(request, area='settings', s=s, auto_ip=auto_ip, has_key=ssh.has_key(),
               line=ssh.authorized_line(s['lxc_ip']) if ssh.has_key() else '',
               guard_url=f'{origin}/host/permlens-guard', guard_sha=guard_sha256(), guard_path=ssh.GUARD,
               guard_new=guard_version(), guard_old=guard_outdated(s['guard']),
               tls_fp=tls.fingerprint() if tls.enabled() else '', https=request.url.scheme == 'https',
               fingerprint=ssh.host_fingerprint(s['host'], s['port']) if s['host'] else '',
               last=scan.latest(), scanning=scan.running(), host_rows=host_rows(), **values, **update_ctx())


def update_ctx():
    st = updates.STATE
    return {'upd_on': updates.enabled(), 'upd_env_off': updates.env_off(), 'upd_info': updates.info(),
            'upd_latest': st['latest'], 'upd_error': st['error'],
            'upd_checked': datetime.fromtimestamp(st['checked']).astimezone().strftime('%d.%m.%Y %H:%M') if st['checked'] else ''}


@app.get('/settings', response_class=HTMLResponse)
def settings_page(request: Request, message: str = '', err: str = ''):
    return templates.TemplateResponse(request, 'settings.html', settings_ctx(request, message=message, err=err))


@app.post('/settings/pve')
def settings_save(request: Request, host: str = Form(''), port: str = Form('22'), lxc_ip: str = Form('')):
    host, lxc_ip, port = host.strip(), lxc_ip.strip(), port.strip() or '22'
    if host and not ssh.valid_host(host):
        return RedirectResponse('/settings?err=' + quote('Die Adresse des Proxmox-Hosts ist ungültig.'), 303)
    if lxc_ip and not ssh.valid_host(lxc_ip):
        return RedirectResponse('/settings?err=' + quote('Die Adresse des PermLens-LXC ist ungültig.'), 303)
    if not port.isdigit() or not 0 < int(port) < 65536:
        return RedirectResponse('/settings?err=' + quote('Der SSH-Port ist ungültig.'), 303)
    s = pve_settings()
    if not s['id']:  # Einrichtung von Hand, noch ohne Proxmox
        if host:
            db.add_host(host, int(port), lxc_ip=lxc_ip)
        db.set_settings(lxc_ip=lxc_ip)
    else:
        if (host, port) != (s['host'], s['port']):
            ssh.forget_host(s['host'], s['port'])  # andere Adresse: alten Host-Schlüssel nicht weiterverwenden
            db.update_host(s['id'], connected=0)
        if host:
            db.update_host(s['id'], host=host, port=int(port), lxc_ip=lxc_ip)
    db.audit('einstellungen', target='verbindung', result='ok', client=client_of(request), host=host, lxc_ip=lxc_ip)
    return RedirectResponse('/settings?message=' + quote('Gespeichert.'), 303)


@app.post('/settings/key')
def settings_key(request: Request):
    ssh.generate_key()
    for h in db.hosts():  # der neue Schlüssel muss erst auf jedem Proxmox eingetragen werden
        db.update_host(h['id'], connected=0)
    db.audit('schluessel', result='neu', client=client_of(request))
    return RedirectResponse('/settings?message=' + quote('Neuer Schlüssel erzeugt. Bitte die Zeile auf dem Proxmox eintragen.') + '#schluessel', 303)


@app.post('/settings/forget-host')
def settings_forget_host(request: Request):
    s = pve_settings()
    if s['host']:
        ssh.forget_host(s['host'], s['port'])
    db.audit('host-schluessel', result='vergessen', client=client_of(request))
    return RedirectResponse('/settings?message=' + quote('Gespeicherter Host-Schlüssel gelöscht.') + '#test', 303)


@app.post('/settings/test', response_class=HTMLResponse)
def settings_test(request: Request):
    s = pve_settings()
    steps, fresh = connect_and_scan(s, client_of(request)) if s['host'] else ([], False)
    if fresh:  # erste erfolgreiche Verbindung: gleich zur Übersicht
        return RedirectResponse('/', 303)
    return templates.TemplateResponse(request, 'settings.html', settings_ctx(request, steps=steps))


@app.post('/settings/setup-new', response_class=HTMLResponse)
def settings_setup_new(request: Request):
    """Neu einrichten (z. B. anderer Proxmox oder neue Adresse): frischen Einrichtungs-Befehl zeigen."""
    return templates.TemplateResponse(request, 'settings.html', settings_ctx(
        request, setup_cmd=setup.command(origin_of(request), setup.renew(), guard_sha256())))


# ---------------------------------------------------------------- Einstellungen: Zwei-Faktor-Anmeldung (ab 0.5.2)
def tfa_ctx(request):
    t = SEC.totp
    pending = '' if t.active else t.pending()
    label = request.url.hostname or 'PermLens'
    return {'tfa_active': t.active, 'tfa_secret': pending, 'tfa_qr': totp.qr_svg(totp.uri(pending, label)) if pending else '',
            'tfa_left': t.recovery_left(), 'tfa_since': t.since()}


def codes_page(request, codes, message):
    """Ersatz-Codes auf einer eigenen Seite: In den Einstellungen gingen sie unter, je nachdem wohin der Browser springt."""
    r = templates.TemplateResponse(request, 'ersatz_codes.html', ctx(request, area='settings', codes=codes, message=message))
    r.headers['cache-control'] = 'no-store'  # nicht im Verlauf oder Cache des Browsers aufheben
    return r


def tfa_back(message='', err=''):
    q = f'?message={quote(message)}' if message else f'?err={quote(err)}'
    return RedirectResponse('/settings' + q + '#anmeldung', 303)


def tfa_code_ok(request, code, action):
    """Code für eine Änderung an der Zwei-Faktor-Anmeldung prüfen, mit derselben Sperre wie beim Anmelden."""
    client = client_of(request)
    if SEC.locked_for(client):
        return False
    if SEC.totp.check(code):
        SEC.succeeded(client)
        return True
    SEC.failed(client)
    db.audit('zwei-faktor', target=action, result='fehler', client=client)
    return False


@app.post('/settings/updates')
def settings_updates(request: Request, on: str = Form('')):
    """Update-Hinweis ein- oder ausschalten (UPDATE_CHECK=0 in der Stack-Datei geht vor)."""
    db.set_settings(update_check='1' if on else '0')
    db.audit('update-hinweis', result='ein' if on else 'aus', client=client_of(request))
    return RedirectResponse('/settings#updates', 303)


@app.post('/settings/updates/check')
def settings_updates_check(request: Request):
    if not updates.enabled():
        return RedirectResponse('/settings#updates', 303)
    updates.check()
    st, i = updates.STATE, updates.info()
    if st['error']:
        q = 'err=' + quote('GitHub ist gerade nicht erreichbar. PermLens versucht es in sechs Stunden wieder.')
    elif i:
        q = 'message=' + quote('Es gibt eine neue Version. Der Link steht unten auf jeder Seite.')
    elif not st['latest']:
        q = 'message=' + quote('Bei GitHub gibt es noch kein öffentliches Release.')
    else:
        q = 'message=' + quote('PermLens ist auf dem neuesten Stand.')
    return RedirectResponse(f'/settings?{q}#updates', 303)


@app.post('/settings/2fa/start')
def tfa_start(request: Request):
    SEC.totp.start()
    return RedirectResponse('/settings#anmeldung', 303)


@app.post('/settings/2fa/cancel')
def tfa_cancel(request: Request):
    if not SEC.totp.active:
        SEC.totp.disable()
    return RedirectResponse('/settings#anmeldung', 303)


@app.post('/settings/2fa/confirm', response_class=HTMLResponse)
def tfa_confirm(request: Request, code: str = Form('')):
    codes = SEC.totp.activate(code)
    if not codes:
        return tfa_back(err='Der Code stimmt nicht. Bitte den aktuellen Code aus der App eingeben (er wechselt alle 30 Sekunden).')
    db.audit('zwei-faktor', target='einschalten', result='ok', client=client_of(request))
    # Neuer Schlüssel: alle anderen Anmeldungen enden, dieser Browser bleibt angemeldet
    return signed_in(request, codes_page(request, codes, 'Zwei-Faktor-Anmeldung ist eingeschaltet.'), code_today=True)


@app.post('/settings/2fa/recovery', response_class=HTMLResponse)
def tfa_recovery(request: Request, code: str = Form('')):
    if not tfa_code_ok(request, code, 'ersatz-codes'):
        return tfa_back(err='Der Code stimmt nicht oder wurde schon benutzt.')
    codes = SEC.totp.new_recovery()
    db.audit('zwei-faktor', target='ersatz-codes', result='neu', client=client_of(request))
    return codes_page(request, codes, 'Neue Ersatz-Codes erzeugt. Die alten gelten nicht mehr.')


@app.post('/settings/2fa/off')
def tfa_off(request: Request, code: str = Form('')):
    if not tfa_code_ok(request, code, 'ausschalten'):
        return tfa_back(err='Der Code stimmt nicht oder wurde schon benutzt.')
    SEC.totp.disable()
    db.audit('zwei-faktor', target='ausschalten', result='ok', client=client_of(request))
    r = signed_in(request, tfa_back(message='Zwei-Faktor-Anmeldung ist ausgeschaltet.'))
    r.delete_cookie(sec.DAY_COOKIE)
    return r


# ---------------------------------------------------------------- Mehrere Proxmox (ab 0.5.0)
def host_rows():
    """Alle Proxmox für die Einstellungen, mit dem Zeitpunkt des letzten Einlesens."""
    rows = []
    for h in db.hosts():
        last = scan.latest(h['id'])
        rows.append({**h, 'finished': (last or {}).get('finished', ''),
                     'lxcs': sum(1 for g in (last or {}).get('guests', []) if g['type'] == 'lxc')})
    return rows


def back_to(request, default='/'):
    """Zurück auf die Seite, von der aus umgeschaltet wurde (nur Seiten von PermLens selbst)."""
    ref = urlsplit(request.headers.get('referer', ''))
    if ref.netloc != request.headers.get('host', '') or not ref.path:
        return default
    # Seiten, die zu einem bestimmten Container oder einer Änderung gehören, passen nach dem Umschalten nicht mehr
    if ref.path.startswith(('/container/', '/aenderung/', '/aenderungen/')) or ref.path == '/diagnose':
        return default
    return safe_next(ref.path + (f'?{ref.query}' if ref.query and ref.path == '/mapping' and 'ct=' not in ref.query else ''))


@app.post('/hosts/{hid}/waehlen')
def host_choose(request: Request, hid: int):
    h = db.host(hid)
    if not h or not same_origin(request):
        return RedirectResponse('/', 303)
    r = RedirectResponse(back_to(request), 303)
    r.set_cookie(HOST_COOKIE, str(hid), max_age=FIVE_YEARS, samesite='lax')
    db.audit('proxmox', target=h['host'], result='gewaehlt', client=client_of(request))
    return r


@app.post('/hosts/{hid}/umbenennen')
def host_rename(request: Request, hid: int, name: str = Form('')):
    name = ' '.join(name.split())[:40]
    if db.host(hid) and name and same_origin(request):
        db.update_host(hid, name=name)
    return RedirectResponse('/settings#proxmox', 303)


@app.post('/hosts/{hid}/entfernen')
def host_remove(request: Request, hid: int):
    """Nur aus PermLens entfernen. Wächter und Schlüssel-Zeile auf dem Proxmox bleiben, bis man sie selbst löscht."""
    h = db.host(hid)
    if not h or not same_origin(request):
        return RedirectResponse('/settings', 303)
    db.delete_host(hid)
    ssh.forget_host(h['host'], h['port'])
    db.audit('proxmox', target=h['host'], result='entfernt', client=client_of(request))
    r = RedirectResponse('/settings?message=' + quote(i18n.tr_text(get_lang(request), '§ ist aus PermLens entfernt. '
                         'Auf dem Proxmox selbst bleiben Wächter und Schlüssel-Zeile, bis du sie löschst (Anleitung: '
                         'SICHERHEIT.md, Abschnitt 9 „Vollständig entfernen“).', h['name'])) + '#proxmox', 303)
    if request.cookies.get(HOST_COOKIE) == str(hid):
        r.delete_cookie(HOST_COOKIE)
    return r


# ---------------------------------------------------------------- Mapping-Assistent (Phase 4)
MAPPING_FIELDS = bauplan.FIELDS


def console_targets(last):
    """Ziele der Konsole: Host, jeder laufende LXC und seine Docker-Apps. [(wert, art, vmid, app, text)]"""
    out = [('host', 'host', None, '', (last or {}).get('host', ''))]
    for g in (last or {}).get('guests', []):
        if g['type'] == 'lxc' and g.get('status') == 'running':
            out.append((str(g['vmid']), 'lxc', g['vmid'], '', f"{g['vmid']} · {g['name']}"))
            for a in docker.apps_of(g):
                out.append((f"{g['vmid']}:{a['name']}", 'app', g['vmid'], a['name'], a['name']))
    return out


def render_console(request, ziel, eingabe='', res=None):
    last = scan.latest()
    targets = console_targets(last)
    t = next((x for x in targets if x[0] == ziel), None) or targets[0]
    recent = [e for e in db.audit_entries(400) if e['action'] == 'konsole'][:10]
    for e in recent:
        e['details'] = json.loads(e['details'] or '{}')
    return templates.TemplateResponse(request, 'konsole.html', ctx(
        request, area='console', last=last, targets=targets, ziel=t[0], kind=t[1], vmid=t[2], app=t[3],
        eingabe=eingabe, res=res, help=console.HELP[t[1]], recent=recent, guard_now=pve_settings()['guard']))


@app.get('/konsole', response_class=HTMLResponse)
def console_page(request: Request, ziel: str = 'host'):
    """„Nachschauen“-Konsole (AP 6.3): feste, lesende Befehle für Host, LXC oder Docker-App."""
    return render_console(request, ziel)


@app.post('/konsole', response_class=HTMLResponse)
def console_run(request: Request, ziel: str = Form('host'), eingabe: str = Form('')):
    if not same_origin(request):
        return RedirectResponse('/konsole', 303)
    eingabe = eingabe.strip()[:500]
    t = next((x for x in console_targets(scan.latest()) if x[0] == ziel), None)
    if not t or not eingabe:
        return render_console(request, ziel, eingabe)
    s = pve_settings()
    res = console.run(s['host'], s['port'], t[1], t[2], t[3], eingabe)
    if res['cmd']:  # nur Befehl und Ergebnis ins Protokoll, nie die Ausgabe
        db.audit('konsole', target=t[0], result='fehler' if res['error'] else 'ok', client=client_of(request),
                 befehl=res['cmd'])
    return render_console(request, t[0], eingabe, res)


@app.get('/mapping', response_class=HTMLResponse)
def mapping_page(request: Request, art: str = 'neu', ct: int = 0):
    q = request.query_params
    form = {k: q.get(k, '') for k in MAPPING_FIELDS + ('more_u', 'more_g')}
    last = scan.latest()
    art = art if art in ('bestehend', 'umstieg') else 'neu'
    plan = bauplan.make(last, form) if art == 'neu' and any(form[f'src{i}'] for i in range(bauplan.MAX_FOLDERS)) else None
    ep = bauplan.existing_plan(last, ct, {'chosen': q.get('chosen', ''), 'u': q.getlist('u'), 'g': q.getlist('g'),
                                          'more_u': q.get('more_u', ''), 'more_g': q.get('more_g', '')}) if art == 'bestehend' and ct else None
    if art == 'umstieg' and ct:
        ep = bauplan.migration_plan(last, ct, {'chosen': q.get('chosen', ''), 'u': q.getlist('u'), 'g': q.getlist('g'),
                                               'more_u': q.get('more_u', ''), 'more_g': q.get('more_g', ''),
                                               'new': q.get('new', ''), 'store': q.get('store', '')})
    lxcs = [g for g in (last or {}).get('guests', []) if g['type'] == 'lxc' and g.get('config')]
    hid = (db.active_host() or {}).get('id')
    saved = [{**p, **bauplan.summary(p['params'])} for p in db.plans(hid)]
    loaded = db.plan(int(q['geladen']), hid) if q.get('geladen', '').isdigit() else None
    source, notes = None, []
    if q.get('aus'):  # vorbelegt aus einer Docker-App: 'vmid:name'
        vm, _, name = q['aus'].partition(':')
        guest = next((g for g in lxcs if str(g['vmid']) == vm), None)
        a = docker.find_app(guest, name) if guest else None
        if a:
            source, notes = {'vmid': guest['vmid'], 'app': name}, bauplan.from_app(guest, a)[1]
    save_name = (loaded or {}).get('name') or (source or {}).get('app', '')
    return templates.TemplateResponse(request, 'mapping.html', ctx(
        request, area='mapping', form=form, plan=plan, known=bauplan.known_folders(last), apps=bauplan.APPS,
        max_folders=bauplan.MAX_FOLDERS, query=request.url.query, art=art, ct=ct, ep=ep, lxcs=lxcs,
        saved=saved, loaded=loaded, source=source, notes=notes, save_name=save_name, name_max=bauplan.NAME_MAX,
        hc=host_change(last, ct) if ct else None,
        message=q.get('message', ''), warn=q.get('warn') == '1'))


# ---------------------------------------------------------------- Gespeicherte Baupläne (AP 6.6)
def plan_url(params, anchor='', **extra):
    """Adresse des Mapping-Assistenten mit diesen Eingaben (und z. B. geladen=…, message=…)."""
    q = urlencode({**params, **{k: v for k, v in extra.items() if v}})
    anchor = anchor or ('bauplan' if any(params.get(f'src{i}') for i in range(bauplan.MAX_FOLDERS)) else '')
    return '/mapping' + (f'?{q}' if q else '') + (f'#{anchor}' if anchor else '')


def plans_url(request, text, *values, warn=False):
    return ('/mapping?' + ('warn=1&' if warn else '') + 'message=' + quote(i18n.tr_text(get_lang(request), text, *values))
            + '#plaene')


@app.post('/mapping/plaene')
async def plan_save(request: Request):
    """Bauplan unter einem Namen speichern (ohne Container-Nummer). Gleicher Name: ersetzt den alten."""
    if not same_origin(request):
        return RedirectResponse('/mapping', 303)
    data = await request.form()
    params, name = bauplan.stored(data), bauplan.clean_name(data.get('name'))
    lang = get_lang(request)
    if not name or bauplan.make(scan.latest(), params)['errors']:
        return RedirectResponse(plan_url(params, 'plaene', warn='1', message=i18n.tr_text(
            lang, 'Bitte einen Namen angeben. Gespeichert wird nur ein Bauplan ohne Fehler.')), 303)
    hid = (db.active_host() or {}).get('id')
    pid, replaced = db.save_plan(hid, name, params)
    db.audit('bauplan', target=name, result='ersetzt' if replaced else 'gespeichert', client=client_of(request))
    msg = 'Bauplan „§“ ersetzt.' if replaced else 'Bauplan „§“ gespeichert.'
    return RedirectResponse(plan_url(params, 'plaene', geladen=str(pid), message=i18n.tr_text(lang, msg, name)), 303)


@app.get('/mapping/plaene/{pid}')
def plan_load(request: Request, pid: int):
    p = db.plan(pid, (db.active_host() or {}).get('id'))
    if not p:
        return RedirectResponse(plans_url(request, 'Diesen Bauplan gibt es nicht (mehr).', warn=True), 303)
    return RedirectResponse(plan_url(p['params'], geladen=str(pid)), 303)


@app.post('/mapping/plaene/{pid}/umbenennen')
def plan_rename(request: Request, pid: int, name: str = Form('')):
    hid = (db.active_host() or {}).get('id')
    p, name = db.plan(pid, hid), bauplan.clean_name(name)
    if not p or not name or not same_origin(request):
        return RedirectResponse('/mapping#plaene', 303)
    other = db.plan_named(hid, name)
    if other and other['id'] != pid:
        return RedirectResponse(plans_url(request, 'Einen Bauplan „§“ gibt es schon.', name, warn=True), 303)
    db.rename_plan(pid, hid, name)
    db.audit('bauplan', target=name, result='umbenannt', client=client_of(request), vorher=p['name'])
    return RedirectResponse(plans_url(request, 'Bauplan heißt jetzt „§“.', name), 303)


@app.post('/mapping/plaene/{pid}/loeschen')
def plan_delete(request: Request, pid: int):
    hid = (db.active_host() or {}).get('id')
    p = db.plan(pid, hid)
    if not p or not same_origin(request):
        return RedirectResponse('/mapping#plaene', 303)
    db.delete_plan(pid, hid)
    db.audit('bauplan', target=p['name'], result='geloescht', client=client_of(request))
    return RedirectResponse(plans_url(request, 'Bauplan „§“ gelöscht.', p['name']), 303)


@app.get('/mapping/aus-app')
def plan_from_app(request: Request, ct: int = 0, app: str = ''):
    """Mapping-Assistent mit dem Vorschlag aus einer laufenden Docker-App vorbelegen (Link im Docker-Reiter)."""
    guest = next((g for g in (scan.latest() or {}).get('guests', []) if g['vmid'] == ct and g['type'] == 'lxc'), None)
    a = docker.find_app(guest, app) if guest else None
    if not a:
        return RedirectResponse('/mapping', 303)
    params, _ = bauplan.from_app(guest, a)
    return RedirectResponse(plan_url(params, aus=f'{ct}:{app}'), 303)


@app.get('/mapping/bauplan.txt', response_class=PlainTextResponse)
def mapping_text(request: Request):
    form = {k: request.query_params.get(k, '') for k in MAPPING_FIELDS}
    plan = bauplan.make(scan.latest(), form)
    if plan['errors']:
        return PlainTextResponse('# ' + '\n# '.join(i18n.tr_text(get_lang(request), *e) for e in plan['errors']) + '\n', 400)
    name = f"permlens-bauplan-{plan['vmid'] or 'neu'}.txt"
    return PlainTextResponse(plan['text'], headers={'Content-Disposition': f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- Änderungen (Phase 3)
CHANGE_FIELDS = ('name', 'gid', 'path', 'uid', 'mode', 'add', 'kind', 'id', 'perm', 'user', 'group', 'old', 'new',
                 'default', 'nr') + hostchange.FIELDS


def same_origin(request):
    """Schreibende Anfragen nur von PermLens selbst (zusätzlich zum SameSite-Cookie)."""
    src = request.headers.get('origin') or request.headers.get('referer')
    return not src or urlsplit(src).netloc == request.headers.get('host', '')


def change_page(request, p, undo_of=None, error=None):
    if error:
        p = {**p, 'error': error}
    if p.get('action') == 'mapping':
        back = f'/mapping?art=bestehend&ct={p["vmid"]}#vorschlag'
    elif p.get('host'):
        back = f'/container/{p["vmid"]}?tab=host'
    elif p.get('action') == 'umnummerieren':
        back = f'/container/{p["vmid"]}?tab=ordner'
    elif p.get('path'):
        back = f'/diagnose?ct={p["vmid"]}&path={quote(p["path"])}#ergebnis'
    elif p.get('action') in change.USER_ACTIONS:
        back = f'/container/{p["vmid"]}?tab=benutzer#benutzer'
    else:
        back = f'/container/{p["vmid"]}?tab=benutzer#gruppen' if p.get('vmid') else '/aenderungen'
    return templates.TemplateResponse(request, 'aenderung.html', ctx(
        request, area='changes', p=p, undo_of=undo_of, ratings=change.RATINGS, back=back, s=pve_settings()))


def plan_for(action, vmid, params):
    """Plan berechnen; bei Ordner-Aktionen vorher den Zustand des Pfads frisch aus dem Container lesen.
    Änderungen am Host (ab Wächter 9) lesen Freigaben, Status und Einstellungen frisch vom Host."""
    s = pve_settings()
    if action in hostchange.ACTIONS:
        return hostchange.plan(action, scan.latest(), vmid, params, hostchange.live(s['host'], s['port'], vmid))
    guest = view.find(scan.latest(), vmid)
    state = None
    if (action in change.PATH_ACTIONS and guest and guest.get('status') == 'running'
            and change.path_ok(guest, params.get('path', ''))):
        state = change.read_state(s['host'], s['port'], vmid, params['path'])
    if (action in change.RECURSIVE + ('umnummerieren', 'uid-aendern', 'gid-aendern') and guest
            and guest.get('status') == 'running' and change.write_allowed(s['write'], vmid)):
        state = {**(state or {}), **change.read_extra(s['host'], s['port'], vmid, action, params, guest)}
    return change.plan(action, guest, params, s['write'], state)


def change_plan(form):
    try:
        vmid = int(form.get('vmid', ''))
    except ValueError:
        vmid = 0
    params = {k: str(form.get(k, '')) for k in CHANGE_FIELDS if k in form}
    return plan_for(str(form.get('action', '')), vmid, params)


@app.post('/aenderung/vorschau', response_class=HTMLResponse)
async def change_preview(request: Request):
    return change_page(request, change_plan(await request.form()))


@app.post('/aenderung/ausfuehren', response_class=HTMLResponse)
async def change_run(request: Request):
    form = await request.form()
    p = change_plan(form)  # frisch berechnet, nicht aus der Vorschau übernommen
    undo_of = int(form['undo_of']) if str(form.get('undo_of', '')).isdigit() else None
    if not same_origin(request):
        return change_page(request, p, undo_of, ('Anfrage nicht von PermLens selbst. Bitte die Seite neu laden.',))
    s = pve_settings()
    if str(form.get('host_id', '')) != str(s['id']):  # z. B. in einem anderen Tab inzwischen umgeschaltet
        return change_page(request, p, undo_of, ('Diese Vorschau gehört zu einem anderen Proxmox. Inzwischen ist § '
                                                 'gewählt. Bitte die Vorschau hier neu erstellen.', s['name']))
    if p['error'] or not p['cmd']:
        return change_page(request, p, undo_of)
    if not p['allowed']:
        return change_page(request, p, undo_of, ('Ändern am Host ist für diesen Container nicht freigegeben.',) if p.get('host')
                           else ('Schreiben ist für diesen Container nicht freigegeben.',))
    if p['rating'] == 'risiko' and str(form.get('confirm', '')).strip() != str(p['vmid']):
        return change_page(request, p, undo_of, ('Zum Bestätigen die Container-Nummer eintippen.',))
    if p.get('need_ack') and form.get('ack') != '1':
        return change_page(request, p, undo_of, ('Bitte bestätigen, dass du die Dateien selbst nachziehst (oder es keine gibt).',))
    if p.get('host'):
        before = ssh.run(s['host'], ['pct', 'config', str(p['vmid'])], s['port'], timeout=30)
        cid = hostchange.execute(p, s['host'], s['port'], client_of(request), undo_of, before.out if before.ok else '')
    else:
        cid = change.execute(p, s['host'], s['port'], client_of(request), undo_of)
    start_scan(s, client_of(request))  # damit die Seiten gleich den neuen Zustand zeigen
    return RedirectResponse(f'/aenderungen?neu={cid}', 303)


@app.get('/aenderungen', response_class=HTMLResponse)
def changes_page(request: Request, neu: int = 0):
    s = pve_settings()
    rows = [r for r in change.entries() if r['host'] == s['host']]  # nur die des gewählten Proxmox
    return templates.TemplateResponse(request, 'aenderungen.html', ctx(
        request, area='changes', rows=rows, new=next((r for r in rows if r['id'] == neu), None),
        ratings=change.RATINGS, s=s, others=len(db.hosts()) > 1,
        host_ids=((scan.latest() or {}).get('host_change') or {}).get('ids', '')))


@app.post('/aenderungen/{cid}/rueckgaengig', response_class=HTMLResponse)
def change_undo(request: Request, cid: int):
    e = change.entry(cid)
    if not e or e['result'] != 'ok' or e['undone_by'] or not e['undo'] or e['host'] != pve_settings()['host']:
        return RedirectResponse('/aenderungen', 303)
    return change_page(request, plan_for(e['undo']['action'], e['vmid'], e['undo']['params']), undo_of=cid)


# ---------------------------------------------------------------- Einrichtung mit einem Befehl
@app.get('/setup/status')
def setup_status():
    """Fragt die Seite mit dem Einrichtungs-Befehl regelmäßig ab. Bei „Neu einrichten“ oder einem weiteren Proxmox
    erst melden, wenn der neue Befehl gelaufen ist. Dann gleich auf den neuen Proxmox umschalten."""
    last = db.get_setting('setup_last_host')
    h = db.host(int(last)) if last.isdigit() else None
    ok = bool(h and h['connected']) and not setup.pending()
    r = JSONResponse({'connected': ok})
    if ok:
        r.set_cookie(HOST_COOKIE, str(h['id']), max_age=FIVE_YEARS, samesite='lax')
    return r


@app.get('/setup/{tok}', response_class=PlainTextResponse)
def setup_script(request: Request, tok: str):
    if not setup.check(tok) or not ssh.has_key() or not setup.valid_origin(origin_of(request)):
        return PlainTextResponse('#!/bin/bash\necho "PermLens: Dieser Einrichtungs-Befehl ist abgelaufen oder schon benutzt. '
                                 'Bitte den aktuellen Befehl aus PermLens kopieren." >&2\nexit 1\n')
    db.audit('einrichtung', result='script', client=client_of(request))
    return PlainTextResponse(setup.script(origin_of(request), tok, guard_sha256()))


@app.post('/setup/{tok}/fertig', response_class=PlainTextResponse)
def setup_finish(request: Request, tok: str, host: str = Form(''), port: str = Form('22'), node: str = Form(''),
                 lxc_ip: str = Form(''), hostkey: str = Form('')):
    if not setup.check(tok):
        return PlainTextResponse('Fehler: Einrichtungs-Code abgelaufen oder schon benutzt.\n', status_code=403)
    err = setup.finish(host.strip(), port.strip(), node.strip(), lxc_ip.strip(), hostkey.strip())
    if err:
        db.audit('einrichtung', target=host, result='fehler', client=client_of(request), grund=err)
        return PlainTextResponse(f'Fehler: {err}\n', status_code=400)
    steps, _ = connect_and_scan(pve_settings(db.host(int(db.get_setting('setup_last_host')))), client_of(request))
    ok = all(x['ok'] for x in steps)
    db.audit('einrichtung', target=host, result='ok' if ok else 'fehler', client=client_of(request), node=node)
    lines = [('OK    ' if x['ok'] else 'FEHLER ') + i18n.tr_text('de', x['name']) for x in steps]
    lines.append('Fertig. PermLens ist mit diesem Proxmox verbunden und liest jetzt ein. Zurück zum Browser.' if ok
                 else 'Die Verbindung klappt noch nicht. Details stehen in PermLens unter Einstellungen.')
    return PlainTextResponse('\n'.join(lines) + '\n')


def guard_sha256():
    return hashlib.sha256(GUARD_FILE.read_bytes()).hexdigest()


def guard_version():
    """Version des Wächter-Scripts, das in PermLens mitgeliefert wird (Zeile VERSION = '2')."""
    m = re.search(r"^VERSION = '(\d+)'", GUARD_FILE.read_text(encoding='utf-8'), re.M)
    return m.group(1) if m else ''


def guard_outdated(installed):
    """True, wenn auf dem Proxmox eine ältere Wächter-Version läuft als die mitgelieferte."""
    return installed.isdigit() and guard_version().isdigit() and int(installed) < int(guard_version())


@app.get('/host/permlens-guard', response_class=PlainTextResponse)
def guard_download():
    """Das Wächter-Script zum Herunterladen auf den Proxmox-Host (öffentlich, enthält keine Geheimnisse)."""
    return PlainTextResponse(GUARD_FILE.read_text(encoding='utf-8'))


@app.get('/lang/{code}')
def set_lang(code: str, next: str = '/'):
    code = code if code in i18n.LANGS else i18n.DEFAULT
    r = RedirectResponse(safe_next(next), 303)
    r.set_cookie(LANG_COOKIE, code, max_age=FIVE_YEARS, samesite='lax')
    return r


@app.get('/healthz')
def healthz():
    return {'ok': True, 'version': config.version()}
