# PermLens betreiben

PermLens läuft als Docker-Container in einem eigenen LXC auf deinem Proxmox und wird am bequemsten über **Dockhand** verwaltet. Ohne Dockhand geht es genauso mit `docker compose`.

> **Wichtig:** PermLens bekommt Zugriff auf deinen Proxmox-Host. Stelle es **nie** ins Internet.

## 1. LXC anlegen

| Einstellung | Wert |
|---|---|
| Vorlage | Debian 13 |
| Art | unprivilegiert |
| Features | `nesting=1`, `keyctl=1` (unter *Optionen → Features*, nötig für Docker) |
| CPU / RAM / Platte | 1 Kern, 512 MB (Swap 512 MB), 8 GB. Gemessen: PermLens braucht im Leerlauf etwa 50 MB, der ganze LXC mit Docker und Hawser etwa 200 MB. |
| Netzwerk | **feste IP-Adresse** (oder eine feste Zuordnung im Router). Der SSH-Schlüssel von PermLens gilt nur von dieser Adresse aus. |

## 2. Docker im LXC

In der Shell des LXC:

```bash
apt-get update && apt-get install -y docker.io
```

Mit Dockhand: In Dockhand eine neue Umgebung für den LXC anlegen (Hawser-Agent) und den angezeigten Befehl im LXC ausführen, so wie bei deinen anderen LXCs.

## 3. PermLens starten

```bash
mkdir -p /opt/permlens/data
```

**Mit Dockhand:** In der Umgebung des LXC einen neuen Stack „permlens“ anlegen und den Inhalt von [`docker-compose.homelab.yml`](../docker-compose.homelab.yml) einfügen. Das Passwort steht nicht in der Datei: Bei den **Variablen des Stacks** eine Variable `APP_PASSWORD` anlegen und als Wert dein Passwort eintragen (mindestens 8 Zeichen). Dann *Deploy* klicken.

**Ohne Dockhand:** `docker-compose.homelab.yml` nach `/opt/permlens/` kopieren, daneben eine Datei `.env` mit der Zeile `APP_PASSWORD=dein-passwort` anlegen und dort `docker compose -f docker-compose.homelab.yml up -d` ausführen.

Danach im Browser `https://<IP-des-LXC>:8443` öffnen und mit dem Passwort anmelden. `http://<IP-des-LXC>:8000` leitet automatisch dorthin um.

Empfohlen: gleich danach unter *Einstellungen → Zwei-Faktor-Anmeldung* einen Code aus einer Authenticator-App dazuschalten ([SICHERHEIT.md, Abschnitt 4b](SICHERHEIT.md#4b-zwei-faktor-anmeldung-ab-permlens-052)).

Tipp: Läuft PermLens allein in einem eigenen LXC, in der Stack-Datei `"80:8000"`, `"443:8443"` und `HTTPS_PORT=443` eintragen. Dann ist es unter `https://<IP-des-LXC>` ohne Portnummer erreichbar.

### HTTPS: die Warnung beim ersten Besuch

PermLens erzeugt beim ersten Start ein **eigenes Zertifikat** (in `/opt/permlens/data/tls/`, 10 Jahre gültig). Weil es keine Zertifizierungsstelle unterschrieben hat, warnt der Browser beim ersten Besuch („Nicht sicher“ bzw. „Diese Verbindung ist nicht privat“). So prüfst du, dass es wirklich dein PermLens ist:

1. Im Browser die Warnung öffnen und das Zertifikat anzeigen. Den **SHA-256-Fingerabdruck** notieren.
2. Im LXC nachsehen: `docker exec permlens openssl x509 -in /app/data/tls/cert.pem -noout -fingerprint -sha256`
3. Stimmen beide überein, die Ausnahme im Browser speichern. Später steht der Fingerabdruck auch unter *Einstellungen*.

Der Einrichtungs-Befehl für den Proxmox legt den Schlüssel dieses Zertifikats fest (`curl --pinnedpubkey`). Der Proxmox lädt dann nur von genau diesem PermLens, eine Zertifizierungsstelle braucht es dafür nicht. Löschst du `/opt/permlens/data/tls/`, erzeugt PermLens beim nächsten Start ein neues Zertifikat. Der Browser warnt dann wieder.

**Ohne HTTPS** (z. B. hinter einem eigenen Proxy, auf eigene Verantwortung): `HTTPS=0` in die Stack-Datei. Dann gelten die Hinweise in [SICHERHEIT.md, Abschnitt 6](SICHERHEIT.md#6-grenzen-die-du-kennen-solltest).

## 4. Mit dem Proxmox verbinden

> **Bitte vorher lesen:** [Sicherheit: Was PermLens auf deinem Proxmox-Host tut](SICHERHEIT.md). Dort steht genau, was der Befehl verändert, was PermLens darf und was im Cluster zu beachten ist.

Beim ersten Öffnen zeigt PermLens **einen einzigen Befehl** an. Den kopierst du in die **Shell des Proxmox-Hosts** (Proxmox-Weboberfläche → Knoten → Shell) und drückst Enter. Mehr ist nicht zu tun:

- Nummer und Adresse des LXC spielen keine Rolle, PermLens und der Befehl finden beides selbst heraus.
- Der Befehl installiert das Wächter-Script `/usr/local/sbin/permlens-guard`. Es prüft jeden Befehl von PermLens und lässt nur erlaubte durch.
- Er erlaubt den Schlüssel von PermLens in `/root/.ssh/authorized_keys`, gebunden an das Wächter-Script und an die Adresse des PermLens-LXC. Er löscht und überschreibt nichts.
- Er meldet PermLens die Adresse, den SSH-Port und den Host-Schlüssel des Proxmox.
- PermLens testet daraufhin die Verbindung, liest alle Container und VMs ein und springt im Browser von selbst zur Übersicht.

Der Befehl enthält einen Einmal-Code. Er gilt eine Stunde und nur für eine Einrichtung.

**Weiteren Proxmox hinzufügen** (ab 0.5.0, unter Einstellungen → Proxmox) zeigt einen neuen Einrichtungs-Befehl. Auf dem weiteren Proxmox ausgeführt, kommt er zur Liste dazu, die bisherigen bleiben. Welchen Proxmox du gerade ansiehst, wählst du unter der Kopfzeile. Jeder hat seinen eigenen eingelesenen Stand. Beim Update von 0.4.x übernimmt PermLens die bisherige Verbindung von selbst, du musst nichts neu einrichten.

**Neu einrichten** (unter Einstellungen) brauchst du nur für ein neues Wächter-Script oder wenn sich die Adresse des PermLens-LXC geändert hat. Für Sonderfälle, z. B. wenn PermLens hinter einem Proxy läuft, gibt es dort auch eine manuelle Einrichtung.

Rückgängig machen: die Zeile mit `permlens` aus `/root/.ssh/authorized_keys` löschen und `/usr/local/sbin/permlens-guard` entfernen. Die sicheren Befehle dafür stehen in [SICHERHEIT.md, Abschnitt 9](SICHERHEIT.md#9-vollständig-entfernen) (die Datei ist bei Proxmox ein Link und gilt im Cluster für alle Knoten). Nach einer Neuinstallation von PermLens bleibt die alte Zeile stehen. Sie ist dann wirkungslos, weil es den alten Schlüssel nicht mehr gibt, und kann gelöscht werden.

Alles, was PermLens auf dem Host aufruft, steht im Systemprotokoll: `journalctl -t permlens`.

## 5. Neue Version einspielen

**Mit Dockhand:** Stack „permlens“ → *Pull* → *Redeploy*. Die Daten in `/opt/permlens/data` bleiben erhalten. Welche Version läuft, steht unten auf jeder Seite. Ab 0.5.7 steht dort auch ein Hinweis, wenn es eine neue Version gibt (Einstellungen → Updates).

**Ohne Dockhand:** `docker compose -f docker-compose.homelab.yml pull && docker compose -f docker-compose.homelab.yml up -d`

**Ab 0.2.1** läuft PermLens im Container nicht mehr als root, sondern als Benutzer `permlens` (UID 10001). Beim ersten Start übergibt PermLens den Ordner `/opt/permlens/data` selbst an diesen Benutzer. Du musst nichts tun. Danach gehören die Dateien dort im LXC der Nummer 10001.

**Ab 0.2.2** spricht PermLens HTTPS. Eine ältere Stack-Datei läuft weiter, PermLens zeigt dann oben einen Hinweis. Umstellen: in der Stack-Datei bei `ports` die Zeile `- "443:8443"` (bzw. `- "8443:8443"`) und bei `environment` die Zeile `- HTTPS_PORT=443` (bzw. `8443`) ergänzen, dann *Redeploy*. Neu einrichten musst du dafür nicht.

**Feste Version statt `:latest`:** Wer Updates selbst steuern will, trägt in der Stack-Datei z. B. `ghcr.io/luro611/permlens:0.2.1` ein und ändert die Nummer bei jedem Update.

## Einstellungen in der Stack-Datei

| Eintrag | Bedeutung |
|---|---|
| `APP_PASSWORD` | **Pflicht**, mindestens 8 Zeichen. In Dockhand als Variable des Stacks, nicht in der Datei selbst. Ohne Passwort zeigt PermLens nur einen Hinweis. Ein neues Passwort meldet alle ab. Passwort vergessen: einfach in Dockhand einen neuen Wert eintragen und den Stack neu starten. Zusätzlich gibt es wahlweise die Zwei-Faktor-Anmeldung (Einstellungen). Handy verloren: `rm /opt/permlens/data/totp.json` im LXC, dann reicht wieder das Passwort. |
| `ALLOW_PUBLIC=0` | Nur Zugriffe aus dem Heimnetz (Standard). Nicht ändern. |
| `HTTPS_PORT` | Port, unter dem HTTPS von außen erreichbar ist (`443` oder `8443`). Ist er gesetzt, leitet PermLens unverschlüsselte Aufrufe auf HTTPS um. |
| `HTTPS=0` | Schaltet HTTPS ab. Nur, wenn ein eigener Proxy davor die Verschlüsselung übernimmt. |
| `TZ=Europe/Berlin` | Zeitzone für die Anzeige. |
| `UPDATE_CHECK=0` | Schaltet den Hinweis „Neue Version verfügbar“ ganz ab. PermLens fragt dann nie bei GitHub nach. Ohne diesen Eintrag lässt er sich unter Einstellungen → Updates ein- und ausschalten. |

## Sichern

Alles, was PermLens braucht, liegt im LXC in `/opt/permlens/data`:

| Datei | Inhalt |
|---|---|
| `permlens.db` | Einstellungen, verbundene Proxmox, eingelesene Stände und das Protokoll der Änderungen mit den Sicherungen für „Rückgängig“ |
| `ssh/` | der SSH-Schlüssel von PermLens und die bekannten Host-Schlüssel der Proxmox |
| `tls/` | das eigene HTTPS-Zertifikat |
| `secret.key` | Schlüssel für die Anmelde-Cookies |
| `totp.json` | nur mit Zwei-Faktor-Anmeldung: der geheime Schlüssel und die Prüfsummen der Ersatz-Codes |

**Am einfachsten** sicherst du den ganzen PermLens-LXC wie deine anderen Container mit der Datensicherung von Proxmox (vzdump). Wer nur den Ordner sichern will: `tar czf permlens-data.tgz -C /opt/permlens data` im LXC.

**Die Sicherung enthält den SSH-Schlüssel zum Proxmox.** Bewahre sie so auf wie andere Zugangsdaten. Wer sie hat und aus dem Heimnetz von der Adresse des PermLens-LXC kommt, kann tun, was das Wächter-Script erlaubt.

**Zurückspielen:** Ordner wieder nach `/opt/permlens/data` legen, Stack starten. Der LXC braucht **dieselbe IP-Adresse** wie vorher, denn der Schlüssel gilt auf dem Proxmox nur von dort (`from="…"`). Bei einer neuen Adresse unter *Einstellungen → Neu einrichten* den Befehl einmal auf jedem Proxmox ausführen.

## Entfernen

PermLens im LXC stoppen und den LXC löschen reicht nicht ganz: Auf jedem verbundenen Proxmox bleiben Wächter-Script und Schlüssel-Zeile, bis du sie entfernst. Die Befehle stehen in [SICHERHEIT.md, Abschnitt 9](SICHERHEIT.md#9-vollständig-entfernen).
