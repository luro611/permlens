<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/logo/luro-siegel-kompakt-dunkel.png"><img src="docs/bilder/logo/luro-siegel-kompakt-hell.png" alt="luro HOMELAB" width="110"></picture>

# PermLens

**Rechte-Manager für LXC-Container**, derzeit speziell für Proxmox VE.

**[Installation](docs/INSTALLATION.md)** ([English](docs/INSTALLATION.en.md)) · **Website: [lurohome.de/permlens](https://lurohome.de/permlens/)** · Docker-Image: `ghcr.io/luro611/permlens` (amd64, arm64) · Lizenz / License: GPL-3.0-or-later

PermLens zeigt, welche Benutzer es in deinen LXC-Containern gibt, wer sie auf dem Proxmox-Host sind (UID/GID-Mapping) und wer auf welche eingehängten Ordner und NAS-Freigaben zugreifen darf. Es erklärt Rechte-Probleme in Klartext, schlägt den passenden Befehl vor und setzt ihn auf Wunsch selbst um, immer mit Vorschau und Rückgängig. Bedienung im Browser, Deutsch und Englisch, hell und dunkel.

> **Wichtig:** PermLens bekommt Zugriff auf deinen Proxmox-Host. Stelle es **nie** ins Internet, sondern nutze es nur im eigenen Heimnetz. Bitte vor der Einrichtung [Sicherheit](#sicherheit) lesen.

**Kein offizielles Proxmox-Projekt.** Proxmox ist eine Marke der Proxmox Server Solutions GmbH.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/uebersicht-dunkel.png"><img src="docs/bilder/uebersicht.png" alt="Übersicht von PermLens: die wichtigsten Probleme, darunter alle Container mit Art, Mapping und Benutzern"></picture>

## In English

PermLens is a **permission manager for LXC containers**, currently built for Proxmox VE. It shows which users exist in your containers, who they are on the host (UID/GID mapping) and who may access which mounted folders and NAS shares. It explains permission problems in plain language, suggests the right command and, if you allow it, applies the fix itself, always with a preview and undo.

- **Is everything all right?** After every scan PermLens checks known sources of trouble on its own: folders seen as `nobody`, missing mount sources, shared folders without setgid, the same name with different numbers, NFS with `no_root_squash` and more.
- **Can X write here?** Pick a container, a user and a folder. PermLens works out whether reading and writing will work, step by step like Linux itself (owner, group, ACL, mapping, every folder on the way), and can double-check by asking the system or with a real write test.
- **Change users and groups:** create users and groups, change memberships, numbers, owners, permissions and ACLs inside the container, also recursively. Only in containers you allow on the Proxmox host, never root or system accounts, never passwords.
- **Make a container unprivileged:** the mapping assistant works out which numbers have to be passed through (`lxc.idmap`, `/etc/subuid`) and writes down every command, with a way back.
- **Docker apps (from 1.1.0):** for every app in an LXC, which number it really writes as (measured from its running programs, `PUID`/`PGID`), who that is on the host, and whether it may write to its folders. Problems such as “app cannot write to /data” are found on their own.
- **Quick look-up (from 1.1.0):** a console that looks like a terminal but only knows fixed, read-only commands (`id`, `ls -ld`, `stat`, `docker ps` …) for the host, an LXC or a Docker app.
- **Safe by design:** PermLens talks to Proxmox only via SSH with its own key, bound to a guard script with a fixed allow list. No API token, no shell. Several Proxmox hosts, two-factor sign-in, HTTPS.

**Installation:** step by step in the **[installation guide](docs/INSTALLATION.en.md)**. In short: create an unprivileged Debian LXC with Docker and a fixed IP, create `/opt/permlens/data`, add [`docker-compose.homelab.yml`](docker-compose.homelab.yml) as a stack in Dockhand (or run it with `docker compose`) with the variable `APP_PASSWORD`, open `https://<IP-of-the-LXC>:8443` and run the one setup command PermLens shows in the Proxmox shell.

Documentation in English: [Installation](docs/INSTALLATION.en.md) · [User manual](docs/MANUAL.md) · [Security](docs/SICHERHEIT.en.md) · [Check and problems](docs/DIAGNOSE.en.md) · [Changing](docs/AENDERN.en.md) · [Mapping](docs/MAPPING.en.md). The operations guide for updates, backup and removal ([BETRIEB.md](docs/BETRIEB.md)) is in German so far; your browser's translate function works fine there.

## Was PermLens kann

### Ist alles in Ordnung?

Nach jedem Einlesen prüft PermLens von selbst bekannte Fehlerquellen: Ordner, die ein Container als `nobody` sieht, fehlende Mount-Quellen, gemeinsame Ordner ohne setgid, gleiche Namen mit verschiedenen Nummern, NFS mit `no_root_squash` und mehr. Jeder Befund mit Erklärung und Befehl.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/probleme-dunkel.png"><img src="docs/bilder/probleme.png" alt="Seite Probleme: jeder Befund mit Erklärung und Befehl zum Kopieren"></picture>

### Kann X hier schreiben?

Container, Benutzer und Ordner wählen. PermLens rechnet aus, ob Lesen und Schreiben klappt, so wie Linux selbst: Besitzer, Gruppe, ACL, Mapping und jeder Ordner auf dem Weg. Zur Sicherheit fragt es auf Wunsch das System selbst oder macht einen echten Schreibtest.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/pruefen-dunkel.png"><img src="docs/bilder/pruefen.png" alt="Prüfen: Lesen ja, Schreiben nein, mit Ursache und Empfehlung"></picture>

### Benutzer und Gruppen ändern

Benutzer und Gruppen anlegen, in Gruppen aufnehmen, Nummern ändern, Besitzer, Rechte und ACLs von Ordnern setzen, auch für ganze Ordnerbäume. Jede Änderung zeigt vorher den genauen Befehl, die Einstufung (harmlos, Vorsicht, Risiko), vorher und nachher und den Weg zurück. Alles steht im Protokoll und lässt sich rückgängig machen.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/vorschau-dunkel.png"><img src="docs/bilder/vorschau.png" alt="Vorschau einer Änderung: Befehl, Einstufung, vorher und nachher, Rückgängig"></picture>

### Container unprivilegiert machen

Der Mapping-Assistent rechnet aus, welche Nummern ein unprivilegierter Container durchreichen muss (`lxc.idmap`, `/etc/subuid`, `/etc/subgid`), damit er weiter in gemeinsame Ordner schreiben kann. Für den Umstieg von privilegiert schreibt er jeden Befehl auf: sichern, als neuer Container wiederherstellen, Mapping, prüfen. Der alte Container bleibt als Rückfall.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/mapping-umstieg-dunkel.png"><img src="docs/bilder/mapping-umstieg.png" alt="Mapping-Assistent: Umstieg von privilegiert auf unprivilegiert"></picture>

### Docker-Apps (ab 1.1.0)

Läuft im LXC Docker, zeigt PermLens je App, als welche Nummer sie wirklich schreibt (gemessen an ihren laufenden Programmen, sonst `PUID`/`PGID` aus der Stack-Datei), wer das auf dem Proxmox ist und ob sie in ihre Ordner schreiben darf. Probleme wie „App kann nicht in /data schreiben“ findet PermLens von selbst, *Prüfen* rechnet für eine App wie für einen Benutzer. Passwörter aus den Umgebungsvariablen gibt der Wächter nie heraus.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/bilder/container-docker-dunkel.png"><img src="docs/bilder/container-docker.png" alt="Reiter Docker: je App schreibt als, im Container, auf dem Proxmox und die Ordner mit Lesen und Schreiben"></picture>

**Außerdem:** die Konsole *Nachschauen* für den schnellen Blick auf Host, Container oder Docker-App, nur feste, lesende Befehle (ab 1.1.0), mehrere Proxmox in einer Oberfläche, die Einstellungen jedes Containers aus `/etc/pve/lxc/<Nr>.conf` mit Erklärung, Zwei-Faktor-Anmeldung, Hinweis auf neue Versionen.

**Warum „PermLens“?** *Perm* steht für *Permissions* (Berechtigungen), *Lens* für die Linse einer Lupe. Zusammen also eine Lupe für Rechte.

<a id="schnellstart"></a>

## Installation

Die ausführliche Anleitung mit Prüfen des Zertifikats, Einstellungen und Hilfe bei Problemen: **[docs/INSTALLATION.md](docs/INSTALLATION.md)** ([English](docs/INSTALLATION.en.md)). Kurz:

1. **LXC für PermLens anlegen:** Debian 13, unprivilegiert, `nesting=1` und `keyctl=1`, **feste IP-Adresse**. 1 Kern, 512 MB RAM und 8 GB reichen.
2. **Docker im LXC:** `apt-get update && apt-get install -y docker.io`. Mit Dockhand: eine Umgebung für den LXC anlegen (Hawser).
3. **Datenordner:** `mkdir -p /opt/permlens/data`
4. **Stack starten:**
   - **Mit Dockhand:** neuen Stack „permlens“ anlegen, den Inhalt von [`docker-compose.homelab.yml`](docker-compose.homelab.yml) einfügen, bei den Variablen des Stacks `APP_PASSWORD` mit deinem Passwort (mindestens 8 Zeichen) anlegen, *Deploy*.
   - **Ohne Dockhand:**
     ```bash
     cd /opt/permlens && curl -O https://raw.githubusercontent.com/luro611/permlens/main/docker-compose.homelab.yml
     ```
     ```bash
     echo 'APP_PASSWORD=dein-passwort' > /opt/permlens/.env && docker compose -f docker-compose.homelab.yml up -d
     ```
5. **Öffnen:** `https://<IP-des-LXC>:8443` und anmelden. Der Browser warnt beim ersten Mal, weil PermLens ein eigenes Zertifikat hat. Wie du den Fingerabdruck prüfst, steht in [INSTALLATION.md](docs/INSTALLATION.md#4-im-browser-öffnen).
6. **Mit dem Proxmox verbinden:** PermLens zeigt **einen** Befehl. Den in der Shell des Proxmox ausführen (Weboberfläche → Knoten → „>_ Shell“). Fertig, PermLens liest alle Container ein.

**Neue Version:** in Dockhand *Pull* und *Redeploy*. Welche Version läuft, steht unten auf jeder Seite, und PermLens zeigt dort auch, wenn es eine neue gibt.

Alles im Detail: [Installation](docs/INSTALLATION.md), [Anleitung](docs/ANLEITUNG.md) und [Betrieb](docs/BETRIEB.md).

## Sicherheit

PermLens braucht Zugriff auf deinen Proxmox-Host. Die Sicherheit hängt nicht davon ab, dass PermLens „brav“ ist: Selbst wer den PermLens-Container komplett übernimmt, darf auf dem Host nur, was das Wächter-Script erlaubt.

- **Genau zwei Änderungen auf dem Host:** das Wächter-Script `/usr/local/sbin/permlens-guard` und eine zusätzliche Zeile in `/root/.ssh/authorized_keys`. Es wird nichts gelöscht oder überschrieben. Der Einrichtungs-Befehl führt sein Script nur aus, wenn die Prüfsumme stimmt.
- **Der Schlüssel ist fest an den Wächter gebunden** (`command=…,restrict,from=<IP des PermLens-LXC>`). Eine Shell gibt es nicht, kein API-Token. Jeder Aufruf steht in `journalctl -t permlens`.
- **Feste Liste:** Lesen von Containern, Benutzern, Mounts, `/etc/subuid` und `/etc/subgid`, dazu Besitzer und Rechte der eingehängten Ordner, nie deren Inhalt. Keine Pakete, keine Dienste, keine Firewall, kein Cluster, keine Passwörter.
- **Cluster:** `authorized_keys` ist bei Proxmox ein Link nach `/etc/pve/priv/` und gilt für alle Knoten. Beim Entfernen nur die `permlens`-Zeile löschen und **kein** `sed -i` verwenden.
- **Verschlüsselt und gehärtet:** HTTPS mit eigenem Zertifikat, dessen Schlüssel der Einrichtungs-Befehl festlegt. Wahlweise Zwei-Faktor-Anmeldung. Das Image läuft ohne root, mit festen, geprüften Paketversionen, SBOM und Herkunftsnachweis.

Alle Einzelheiten und die ehrlichen Grenzen: **[docs/SICHERHEIT.md](docs/SICHERHEIT.md)** ([English](docs/SICHERHEIT.en.md)).

### Ändern freischalten

Ohne weiteres Zutun **liest** PermLens nur. Ändern geht erst, wenn du auf dem Proxmox eine Datei mit den Containern anlegst, in denen PermLens ändern darf, z. B.:

```bash
mkdir -p /etc/permlens && echo '105,110-112' > /etc/permlens/schreiben-erlaubt
```

Alle anderen Container bleiben nur lesbar. Datei löschen, und PermLens liest sofort wieder nur. Nie root, nie Systemkonten, nie Systemordner, nie Passwörter. Mehr: [docs/AENDERN.md](docs/AENDERN.md).

### Entfernen

Auf dem Proxmox die `permlens`-Zeile aus `authorized_keys` entfernen und das Wächter-Script löschen. Die genauen Befehle (sicher auch im Cluster) stehen in [SICHERHEIT.md, Abschnitt 9](docs/SICHERHEIT.md#9-vollständig-entfernen). Danach den PermLens-LXC löschen.

## Dokumentation

- [Installation](docs/INSTALLATION.md): Schritt für Schritt vom leeren Proxmox bis zur Übersicht, mit Hilfe bei Problemen ([English](docs/INSTALLATION.en.md))
- [Anleitung](docs/ANLEITUNG.md): die Oberfläche, die vier Aufgaben Schritt für Schritt (englisch: [User manual](docs/MANUAL.md))
- [Betrieb](docs/BETRIEB.md): neue Version, Neu einrichten, Sichern, Entfernen
- [Sicherheit](docs/SICHERHEIT.md): was PermLens auf dem Proxmox darf, Firewall, Grenzen ([English](docs/SICHERHEIT.en.md))
- [Prüfen und Probleme](docs/DIAGNOSE.md): wie PermLens rechnet, alle Befunde ([English](docs/DIAGNOSE.en.md))
- [Ändern](docs/AENDERN.md): jede Aktion mit Befehl, Einstufung und Rückgängig ([English](docs/AENDERN.en.md))
- [Mapping](docs/MAPPING.md): unprivilegierte Container mit Zugriff auf Ordner des Hosts ([English](docs/MAPPING.en.md))
- [Änderungen](CHANGELOG.md)

## Grenzen

- **Proxmox VE** mit LXC-Containern. VMs erscheinen nur in der Liste, ein Blick hinein ist für später geplant.
- **Nichts am Proxmox selbst:** Mapping, Mount-Punkte und `/etc/subuid` zeigt PermLens als Befehle, ausführen machst du sie.
- **Nichts auf einem NAS:** Rechte-Listen einer Synology, UGREEN oder TrueNAS kann PermLens nicht lesen. Es sagt dir aber, wenn die Lösung dort liegt.
- **Keine Samba-Passwörter und keine `smb.conf`.**
- **Cluster:** Die Liste zeigt die Gäste aller Knoten, Einzelheiten gibt es aber nur für Container auf dem verbundenen Knoten. Mehrere Proxmox lassen sich einzeln verbinden.

## Hinweise

PermLens ist ein privates Hobbyprojekt, gebaut von [luro](https://lurohome.de) mit Hilfe von KI. Entwickelt und geprüft wird es auf einem eigenen Test-Proxmox mit Test-Containern. Für den Betrieb im eigenen Heimnetz gedacht. Keine Verbindung zu und keine Unterstützung durch Proxmox Server Solutions.

Fehler gefunden oder eine Idee? Gern als [Issue auf GitHub](https://github.com/luro611/permlens/issues).

## Haftungshinweis

PermLens wird kostenlos unter der GNU GPL-3.0-or-later bereitgestellt. Eine Gewährleistung wird nicht übernommen, soweit das gesetzlich zulässig ist. Die Nutzung erfolgt auf eigenes Risiko, besonders beim Ändern von Rechten. Die Software ist nicht in allen Umgebungen getestet. Es besteht keine Verpflichtung zu Support, Fehlerbehebung oder Weiterentwicklung.

*In English:* PermLens is a private hobby project, provided free of charge under the GNU GPL-3.0-or-later. To the extent permitted by law, no warranty is given. Use at your own risk, especially when changing permissions. The software has not been tested in every environment. There is no obligation to provide support.

## Lizenz

GNU GPL v3 oder später, siehe [LICENSE](LICENSE). Die Schriften in `static/fonts/` stehen unter der SIL Open Font License 1.1, siehe [static/fonts/LIZENZEN.md](static/fonts/LIZENZEN.md). Das luro-Siegel gehört zu [lurohome.de](https://lurohome.de).
