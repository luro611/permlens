# PermLens betreiben

PermLens läuft als Docker-Container in einem eigenen LXC auf deinem Proxmox und wird am bequemsten über **Dockhand** verwaltet. Ohne Dockhand geht es genauso mit `docker compose`.

**Zum ersten Einrichten:** [INSTALLATION.md](INSTALLATION.md) ([English](INSTALLATION.en.md)): LXC anlegen, Docker, Stack starten, Zertifikat prüfen, mit dem Proxmox verbinden, Ändern freischalten und alle Einstellungen der Stack-Datei. Diese Seite beschreibt alles danach.

> **Wichtig:** PermLens bekommt Zugriff auf deinen Proxmox-Host. Stelle es **nie** ins Internet.

## Neu einrichten

**Neu einrichten** (unter *Einstellungen*) brauchst du nur für ein neues Wächter-Script oder wenn sich die Adresse des PermLens-LXC geändert hat. Es zeigt einen neuen Befehl für die Shell des Proxmox, wie bei der Installation. Für Sonderfälle, z. B. wenn PermLens hinter einem Proxy läuft, gibt es dort auch eine manuelle Einrichtung.

Nach einer Neuinstallation von PermLens bleibt die alte Zeile in `/root/.ssh/authorized_keys` stehen. Sie ist dann wirkungslos, weil es den alten Schlüssel nicht mehr gibt, und kann gelöscht werden (sicher, auch im Cluster: [SICHERHEIT.md, Abschnitt 9](SICHERHEIT.md#9-vollständig-entfernen)).

Der Fingerabdruck des HTTPS-Zertifikats steht unter *Einstellungen*. Löschst du `/opt/permlens/data/tls/`, erzeugt PermLens beim nächsten Start ein neues Zertifikat. Der Browser warnt dann wieder, und auf jedem Proxmox muss einmal „Neu einrichten“ laufen, weil der Einrichtungs-Befehl den Schlüssel des Zertifikats festlegt.

## Neue Version einspielen

**Mit Dockhand:** Stack „permlens“ → *Pull* → *Redeploy*. Die Daten in `/opt/permlens/data` bleiben erhalten. Welche Version läuft, steht unten auf jeder Seite. Ab 0.5.7 steht dort auch ein Hinweis, wenn es eine neue Version gibt (Einstellungen → Updates).

**Ohne Dockhand:** `docker compose -f docker-compose.homelab.yml pull && docker compose -f docker-compose.homelab.yml up -d`

**Für ältere Installationen:** **Ab 0.2.1** läuft PermLens im Container nicht mehr als root, sondern als Benutzer `permlens` (UID 10001). Beim ersten Start übergibt PermLens den Ordner `/opt/permlens/data` selbst an diesen Benutzer. Du musst nichts tun. Danach gehören die Dateien dort im LXC der Nummer 10001.

**Ab 0.2.2** spricht PermLens HTTPS. Eine ältere Stack-Datei läuft weiter, PermLens zeigt dann oben einen Hinweis. Umstellen: in der Stack-Datei bei `ports` die Zeile `- "443:8443"` (bzw. `- "8443:8443"`) und bei `environment` die Zeile `- HTTPS_PORT=443` (bzw. `8443`) ergänzen, dann *Redeploy*. Neu einrichten musst du dafür nicht.

**Feste Version statt `:latest`** und alle anderen Einträge der Stack-Datei: [INSTALLATION.md, Einstellungen in der Stack-Datei](INSTALLATION.md#einstellungen-in-der-stack-datei).

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
