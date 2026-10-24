"""Klartext für Nicht-Fachleute (Wunsch von Lutz, 0.5.1): Was ist das für ein Benutzer oder eine Gruppe,
und was darf ein Benutzer in den eingehängten Ordnern, und warum?

Alle Texte sind Tupel (Text, Werte …) wie im Rest von PermLens; die Vorlage übersetzt jedes Teil einzeln.
Ein Satz besteht deshalb oft aus mehreren Teilen (z. B. „Der Besitzer darf hier:“ + „lesen und schreiben“)."""
from . import mapping as M

NOLOGIN = ('nologin', '/bin/false', '/usr/bin/false', '/sbin/halt', '/bin/sync')

# Bekannte Systembenutzer (Debian/Ubuntu) und wofür sie da sind
SYSTEM = {
    'daemon': 'Alter Sammel-Benutzer für Hintergrunddienste.',
    'bin': 'Alter Systembenutzer für Programmdateien, wird kaum noch genutzt.',
    'sys': 'Alter Systembenutzer, wird kaum noch genutzt.',
    'sync': 'Hilfsbenutzer zum Schreiben der Festplatten-Puffer.',
    'games': 'Für Spiele, in Containern unbenutzt.',
    'man': 'Für die Hilfeseiten (man).',
    'lp': 'Für Drucker.',
    'mail': 'Für E-Mail.',
    'news': 'Für Newsgroups, in Containern unbenutzt.',
    'uucp': 'Alter Übertragungsdienst, in Containern unbenutzt.',
    'proxy': 'Für Proxy-Dienste.',
    'www-data': 'Unter diesem Namen laufen Webserver wie nginx oder Apache.',
    'backup': 'Für Sicherungen.',
    'list': 'Für Mailinglisten.',
    'irc': 'Für Chat-Dienste (IRC), in Containern unbenutzt.',
    'gnats': 'Alter Fehlermelde-Dienst, in Containern unbenutzt.',
    '_apt': 'Lädt Updates herunter (apt).',
    'systemd-network': 'Verwaltet das Netzwerk (systemd).',
    'systemd-resolve': 'Löst Namen in Adressen auf (DNS, systemd).',
    'systemd-timesync': 'Stellt die Uhrzeit (systemd).',
    'messagebus': 'Nachrichten zwischen Systemdiensten (D-Bus).',
    'sshd': 'Für die Anmeldung per SSH.',
    'postfix': 'Versendet E-Mails (Postfix).',
    'postgres': 'Datenbank PostgreSQL.',
    'mysql': 'Datenbank MySQL oder MariaDB.',
    'redis': 'Zwischenspeicher-Datenbank Redis.',
    'avahi': 'Findet Geräte im Heimnetz (Avahi, mDNS).',
    'ntp': 'Stellt die Uhrzeit (NTP).',
    '_chrony': 'Stellt die Uhrzeit (chrony).',
    'tss': 'Für den Sicherheitschip (TPM).',
    'polkitd': 'Regelt Berechtigungen von Systemdiensten (polkit).',
    'tcpdump': 'Für das Mitschneiden von Netzwerkverkehr.',
}

# Namen von Programmen, die oft eigene Benutzer anlegen
APPS = {'paperless': 'paperless-ngx', 'immich': 'Immich', 'jellyfin': 'Jellyfin', 'plex': 'Plex', 'emby': 'Emby',
        'nextcloud': 'Nextcloud', 'syncthing': 'Syncthing', 'sonarr': 'Sonarr', 'radarr': 'Radarr', 'lidarr': 'Lidarr',
        'prowlarr': 'Prowlarr', 'sabnzbd': 'SABnzbd', 'transmission': 'Transmission', 'debian-transmission': 'Transmission',
        'qbittorrent': 'qBittorrent', 'navidrome': 'Navidrome', 'photoprism': 'PhotoPrism', 'audiobookshelf': 'Audiobookshelf',
        'vaultwarden': 'Vaultwarden', 'homeassistant': 'Home Assistant', 'mediadb': 'MediaDB', 'docker': 'Docker'}

# Was r, w und x bei einem Ordner zusammen bedeuten
PERM = {
    'rwx': 'lesen und schreiben.',
    'r-x': 'lesen, aber nicht schreiben.',
    'r--': 'nur die Namen der Dateien sehen, aber nichts öffnen.',
    '--x': 'hineingehen, aber nichts auflisten.',
    '-wx': 'Dateien hineinlegen, aber nichts auflisten.',
    'rw-': 'fast nichts: ohne x kommt man nicht hinein.',
    '-w-': 'nichts: ohne x kommt man nicht hinein.',
    '---': 'nichts.',
}


def _app(name):
    n = name.lower()
    return next((app for key, app in APPS.items() if n == key or n.startswith(key)), '')


def user_role(u, cfg, shares, owned):
    """Wofür es diesen Benutzer gibt. u: Zeile aus view.container (mit host_uid). Gibt eine Liste von Sätzen zurück."""
    out = []
    unpriv = bool(cfg.get('unprivileged'))
    if u['uid'] == 0:
        out.append(('Der Verwalter (Administrator) des Containers. Er darf im Container alles.',))
        if unpriv:
            out.append(('Weil der Container unprivilegiert ist, ist root auf dem Proxmox nur die Nummer § und hat dort '
                        'keine Sonderrechte. Das ist so gewollt und schützt den Proxmox.', u['host_uid']))
        else:
            out.append(('Weil der Container privilegiert ist, ist root hier auch auf dem Proxmox root.',))
        return out
    if u['uid'] == M.NOBODY:
        return [('Platzhalter für „unbekannt“. Dateien, deren Besitzer der Container nicht kennt, erscheinen unter '
                 'diesem Namen.',)]
    if u['system']:
        out.append((SYSTEM[u['name']],) if u['name'] in SYSTEM else
                   ('Gehört zum Betriebssystem oder zu einem installierten Dienst.',))
        return out
    if any(u.get('shell', '').endswith(x) for x in NOLOGIN):
        out.append(('Dienst-Konto: Ein Programm läuft unter diesem Namen. Anmelden kann man sich damit nicht.',))
    else:
        out.append(('Persönliches Konto: Man kann sich damit im Container anmelden.',))
    if _app(u['name']):
        out.append(('Der Name passt zu §. Vermutlich hat das Programm diesen Benutzer angelegt.', _app(u['name'])))
    elif u['uid'] == 1000:
        out.append(('Nummer 1000 ist meist der erste Benutzer, der beim Einrichten angelegt wurde.',))
    for sh in shares:
        if sh.get('as_user') == u['name']:
            out.append(('Wer sich über die Samba-Freigabe [§] anmeldet, schreibt als dieser Benutzer.', sh['name']))
    if owned:
        out.append(('Ihm gehören diese eingehängten Ordner: §.', ', '.join(owned)))
    if u['host_uid'] is None:
        out.append(('Seine Nummer ist auf dem Proxmox nicht abgebildet. Was er in eingehängte Ordner schreibt, '
                    'lässt sich dort keinem Benutzer zuordnen.',))
    elif not unpriv:
        out.append(('Auf dem Proxmox ist es dieselbe Nummer §, weil der Container privilegiert ist.', u['uid']))
    elif u['host_uid'] == u['uid']:
        out.append(('Diese Nummer wird durchgereicht: Auf dem Proxmox ist es ebenfalls die Nummer §. So passen '
                    'Dateien in gemeinsamen Ordnern zusammen.', u['uid']))
    else:
        out.append(('Auf dem Proxmox wird daraus die Nummer §. Was dieser Benutzer in eingehängte Ordner schreibt, '
                    'gehört dort der Nummer §.', u['host_uid'], u['host_uid']))
    return out


def group_role(g, users, owned):
    """Wofür es diese Gruppe gibt. users: Benutzer des Containers (Rohdaten mit name, gid)."""
    primary = [u['name'] for u in users if u['gid'] == g['gid']]
    out = []
    if g['name'] in primary and not g['members']:
        out.append(('Eigene Gruppe von § (gleicher Name). Unter Linux bekommt jeder Benutzer so eine Gruppe.', g['name']))
    elif g['members'] or primary:
        out.append(('Gemeinsame Gruppe: Alle Mitglieder dürfen, was die Gruppe darf. So können mehrere Benutzer '
                    'oder Programme denselben Ordner nutzen.',))
    else:
        out.append(('Noch ohne Mitglieder.',))
    if owned:
        out.append(('Ihr gehören diese eingehängten Ordner: §.', ', '.join(owned)))
    return out


def folder_access(name, res, groups, unprivileged=False):
    """Ein Ordner für einen Benutzer: {'read', 'write', 'why': [Sätze], 'perm': 'rwx' oder ''}.
    res: Ergebnis von view.diagnose; groups: {gid: Name} des Containers."""
    if res is None:
        return None
    out = {'read': res['read'], 'write': res['write'], 'why': [], 'perm': ''}
    cause = res['cause']
    if cause == 'offline':
        out['why'].append(('Der Ordner antwortet gerade nicht. Meist ist das NAS dahinter ausgeschaltet.',))
        return out
    if cause == 'fehlt':
        out['why'].append(('PermLens kennt die Rechte dieses Ordners nicht.',))
        return out
    if cause == 'weg':
        stop = next((s['path'] for s in res['steps'] if not s['ok']), '')
        out['why'].append(('§ kommt gar nicht hinein: Der Ordner § auf dem Weg dorthin lässt ihn nicht durch.', name, stop))
        return out
    step = res['steps'][-1] if res['steps'] else None
    why = (step or {}).get('why') or ('',)
    key, args = why[0], why[1:]
    perm = args[-1] if args and isinstance(args[-1], str) and len(args[-1]) == 3 else ''
    out['perm'] = perm
    if key == 'root darf alles':
        out['why'].append(('root darf hier alles, weil der Besitzer des Ordners im Container bekannt ist.',)
                          if unprivileged else ('root darf im privilegierten Container alles.',))
    elif key.startswith('Besitzer'):
        out['why'] += [('§ ist der Besitzer des Ordners. Der Besitzer darf hier:', name), (PERM.get(perm, perm),)]
    elif key.startswith('ACL für den Benutzer'):
        out['why'] += [('Für § gibt es einen eigenen Eintrag (ACL). Er erlaubt:', name), (PERM.get(perm, perm),)]
    elif key.startswith('Gruppe des Ordners'):
        out['why'] += [('Der Ordner gehört der Gruppe §, und § ist darin Mitglied. Die Gruppe darf hier:',
                        groups.get(args[0], args[0]), name), (PERM.get(perm, perm),)]
    elif key.startswith('ACL für Gruppe'):
        out['why'] += [('§ ist in der Gruppe §, die einen eigenen Eintrag (ACL) hat. Er erlaubt:',
                        name, groups.get(args[0], args[0])), (PERM.get(perm, perm),)]
    elif key.startswith('andere') and cause == 'nobody':
        out['why'] += [('Der Ordner gehört auf dem Proxmox einer Nummer, die dieser Container nicht kennt (nobody). '
                        'Deshalb zählt für § nur, was „alle anderen“ dürfen:', name), (PERM.get(perm, perm),)]
        return out
    elif key.startswith('andere'):
        out['why'] += [('§ ist weder Besitzer des Ordners noch in seiner Gruppe. Dann gilt, was „alle anderen“ '
                        'dürfen:', name), (PERM.get(perm, perm),)]
    if cause == 'nobody':
        out['why'].append(('Der Ordner gehört auf dem Proxmox einer Nummer, die dieser Container nicht kennt '
                           '(nobody). Deshalb zählen nur die Rechte für „alle anderen“.',))
    if cause == 'nur-lesen' and res['read']:
        out['why'].append(('Schreiben geht trotzdem nicht: Der Ordner ist nur zum Lesen eingehängt.',))
    return out


# Zeilen aus /etc/pve/lxc/<Nr>.conf (0.5.6, nur anzeigen). Wichtig sind die Zeilen, die Rechte und Mapping bestimmen.
CONF = {
    'unprivileged': 'Bei 1 ist der Container unprivilegiert: Seine Nummern werden auf dem Host verschoben '
                    '(meist um 100000). Fehlt die Zeile, ist er privilegiert.',
    'mp': 'Eingehängter Ordner: zuerst die Quelle auf dem Host (oder ein Speicher von Proxmox), mp= ist das Ziel '
          'im Container, ro=1 heißt nur lesen.',
    'lxc.mount.entry': 'Eingehängter Ordner als LXC-Zeile, an der Oberfläche von Proxmox vorbei: Quelle auf dem Host, '
                       'Ziel im Container (ohne / am Anfang), Optionen.',
    'lxc.idmap': 'Eigenes Mapping: u für Benutzer, g für Gruppen, dann Nummer im Container, Nummer auf dem Host und '
                 'Anzahl. Was hier fehlt, sieht der Container als nobody.',
    'lxc': 'Eigene LXC-Einstellung, an der Oberfläche von Proxmox vorbei.',
    'features': 'Zusatzfunktionen: nesting=1 brauchen Docker und neuere systemd, keyctl=1 braucht Docker im '
                'unprivilegierten Container, mount=nfs;cifs erlaubt eigene Netzlaufwerke im Container.',
    'rootfs': 'Das Systemlaufwerk des Containers.',
    'hostname': 'Name des Containers im Netz.',
    'net': 'Netzwerkkarte mit Adresse (ip=) und Bridge.',
    'onboot': 'Bei 1 startet der Container mit dem Proxmox.',
    'ostype': 'Betriebssystem im Container.',
    'tags': 'Schlagwörter aus der Oberfläche von Proxmox.',
    'dev': 'Durchgereichtes Gerät des Hosts (z. B. Grafikkarte).',
    'protection': 'Bei 1 lässt sich der Container nicht löschen.',
    'lock': 'Der Container ist gerade gesperrt, z. B. während einer Sicherung.',
}
CONF_KEY = ('unprivileged', 'mp', 'lxc.mount.entry', 'lxc.idmap', 'lxc', 'features')


def _conf_kind(key):
    if key.startswith('mp') and key[2:].isdigit():
        return 'mp'
    if key.startswith('net') and key[3:].isdigit():
        return 'net'
    if key.startswith('dev') and key[3:].isdigit():
        return 'dev'
    if key.startswith('lxc.') and key not in CONF:
        return 'lxc'
    return key


def conf(cfg):
    """Zeilen der conf mit Erklärung: [{key, value, note, key_line}]. None, wenn der Stand älter als 0.5.6 ist."""
    if 'lines' not in (cfg or {}):
        return None
    out, seen = [], set()
    for key, value in cfg['lines']:
        kind = _conf_kind(key)
        out.append({'key': key, 'value': value, 'note': '' if kind in seen else CONF.get(kind, ''),
                    'key_line': kind in CONF_KEY})  # Erklärung nur bei der ersten Zeile jeder Art (mp0, mp1 …)
        seen.add(kind)
    return out
