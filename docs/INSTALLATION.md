# PermLens installieren

*English version: [INSTALLATION.en.md](INSTALLATION.en.md)*

Diese Anleitung führt Schritt für Schritt von einem leeren Proxmox bis zur ersten Übersicht in PermLens. Rechne mit etwa 15 Minuten.

PermLens läuft als Docker-Container in einem eigenen LXC auf deinem Proxmox. Am bequemsten verwaltest du es mit **Dockhand**, ohne Dockhand geht es genauso mit `docker compose`.

> **Wichtig:** PermLens bekommt Zugriff auf deinen Proxmox-Host. Stelle es **nie** ins Internet, sondern nutze es nur im eigenen Heimnetz. Bitte vor Schritt 5 [SICHERHEIT.md](SICHERHEIT.md) lesen.

## Was du brauchst

- Einen **Proxmox VE** mit Zugang zur Weboberfläche und zur Shell des Knotens (als root).
- Eine **freie, feste IP-Adresse** im Heimnetz für den PermLens-LXC, z. B. außerhalb des DHCP-Bereichs deines Routers oder mit fester Zuordnung im Router.
- Eine Debian-13-Vorlage für Container (in Proxmox: *local → CT-Vorlagen → Vorlagen*).
- Wahlweise **Dockhand**, wenn du deine Docker-Stacks schon damit verwaltest.

## 1. LXC anlegen

In der Proxmox-Weboberfläche *Erstelle CT* mit diesen Werten:

| Einstellung | Wert |
|---|---|
| Vorlage | Debian 13 |
| Art | **unprivilegiert** (Haken bei „Unprivilegierter Container“ bleibt gesetzt) |
| CPU / RAM / Platte | 1 Kern, 512 MB (Swap 512 MB), 8 GB. Gemessen: PermLens braucht im Leerlauf etwa 50 MB, der ganze LXC mit Docker und Hawser etwa 200 MB. |
| Netzwerk | **feste IP-Adresse**, z. B. `192.168.1.50/24` mit deinem Router als Gateway. Der SSH-Schlüssel von PermLens gilt später nur von dieser Adresse aus. |

Nach dem Anlegen unter *Optionen → Features* **`nesting`** und **`keyctl`** einschalten (nötig für Docker). Dann den Container starten.

## 2. Docker im LXC

In der Shell des LXC (Proxmox-Weboberfläche → Container → *Konsole*):

```bash
apt-get update && apt-get install -y docker.io
```

**Mit Dockhand:** In Dockhand eine neue Umgebung für den LXC anlegen (Hawser-Agent) und den angezeigten Befehl im LXC ausführen, so wie bei deinen anderen LXCs. Dockhand zeigt die Umgebung danach als verbunden.

## 3. PermLens starten

Zuerst den Datenordner anlegen, ebenfalls in der Shell des LXC:

```bash
mkdir -p /opt/permlens/data
```

**Mit Dockhand:** In der Umgebung des LXC einen neuen Stack „permlens“ anlegen und den Inhalt von [`docker-compose.homelab.yml`](../docker-compose.homelab.yml) einfügen. Das Passwort steht nicht in der Datei: Bei den **Variablen des Stacks** eine Variable `APP_PASSWORD` anlegen und als Wert dein Passwort eintragen (mindestens 8 Zeichen). Dann *Deploy* klicken.

**Ohne Dockhand:** im LXC

```bash
cd /opt/permlens && curl -O https://raw.githubusercontent.com/luro611/permlens/main/docker-compose.homelab.yml
```

```bash
echo 'APP_PASSWORD=dein-passwort' > /opt/permlens/.env && docker compose -f docker-compose.homelab.yml up -d
```

Ob PermLens läuft, zeigt `docker ps` (Container `permlens`, Status *Up*) bzw. Dockhand. Die Meldungen beim Start siehst du mit `docker logs permlens`.

Tipp: Läuft PermLens allein in einem eigenen LXC, in der Stack-Datei `"80:8000"`, `"443:8443"` und `HTTPS_PORT=443` eintragen. Dann ist es unter `https://<IP-des-LXC>` ohne Portnummer erreichbar.

## 4. Im Browser öffnen

`https://<IP-des-LXC>:8443` öffnen und mit dem Passwort anmelden. `http://<IP-des-LXC>:8000` leitet automatisch dorthin um.

**Die Warnung beim ersten Besuch:** PermLens erzeugt beim ersten Start ein **eigenes Zertifikat** (in `/opt/permlens/data/tls/`, 10 Jahre gültig). Weil keine Zertifizierungsstelle es unterschrieben hat, warnt der Browser („Nicht sicher“ bzw. „Diese Verbindung ist nicht privat“). So prüfst du, dass es wirklich dein PermLens ist:

1. Im Browser die Warnung öffnen und das Zertifikat anzeigen. Den **SHA-256-Fingerabdruck** notieren.
2. Im LXC nachsehen:
   ```bash
   docker exec permlens openssl x509 -in /app/data/tls/cert.pem -noout -fingerprint -sha256
   ```
3. Stimmen beide überein, die Ausnahme im Browser speichern. Später steht der Fingerabdruck auch unter *Einstellungen*.

Der Einrichtungs-Befehl im nächsten Schritt legt den Schlüssel dieses Zertifikats fest (`curl --pinnedpubkey`). Der Proxmox lädt dann nur von genau diesem PermLens.

**Empfohlen:** gleich nach der ersten Anmeldung unter *Einstellungen → Zwei-Faktor-Anmeldung* einen Code aus einer Authenticator-App dazuschalten ([SICHERHEIT.md, Abschnitt 4b](SICHERHEIT.md#4b-zwei-faktor-anmeldung-ab-permlens-052)).

## 5. Mit dem Proxmox verbinden

> **Bitte vorher lesen:** [Sicherheit: Was PermLens auf deinem Proxmox-Host tut](SICHERHEIT.md). Dort steht genau, was der Befehl verändert, was PermLens darf und was im Cluster zu beachten ist.

Nach der Anmeldung zeigt PermLens **einen einzigen Befehl**. Den kopierst du in die **Shell des Proxmox-Hosts** (Proxmox-Weboberfläche → Knoten → *>_ Shell*) und drückst Enter. Er zeigt drei Schritte:

1. **Wächter-Script installieren:** `/usr/local/sbin/permlens-guard`. Es prüft jeden Befehl von PermLens und lässt nur erlaubte durch.
2. **Schlüssel von PermLens erlauben:** eine zusätzliche Zeile in `/root/.ssh/authorized_keys`, gebunden an das Wächter-Script und an die Adresse des PermLens-LXC. Es wird nichts gelöscht oder überschrieben.
3. **PermLens Bescheid geben:** Adresse, SSH-Port und Host-Schlüssel des Proxmox.

PermLens testet daraufhin die Verbindung, liest alle Container und VMs ein und springt im Browser von selbst zur Übersicht. **Fertig.**

Nummer und Adresse des LXC musst du nirgends eintragen, PermLens und der Befehl finden beides selbst heraus. Der Befehl führt sein Script nur aus, wenn die Prüfsumme stimmt. Er enthält einen Einmal-Code und gilt eine Stunde und nur für eine Einrichtung.

Alles, was PermLens auf dem Host aufruft, steht danach im Systemprotokoll: `journalctl -t permlens`.

**Weiterer Proxmox:** Unter *Einstellungen → Proxmox* zeigt „Weiteren Proxmox hinzufügen …“ einen neuen Befehl. Auf dem weiteren Proxmox ausgeführt, kommt er zur Liste dazu. Welchen Proxmox du gerade ansiehst, wählst du unter der Kopfzeile.

## 6. Ändern freischalten (wahlweise)

Bis hierher **liest** PermLens nur. Wenn PermLens auch Benutzer, Gruppen und Rechte in Containern ändern soll, legst du auf dem Proxmox eine Datei mit den erlaubten Container-Nummern an, z. B.:

```bash
mkdir -p /etc/permlens && echo '105,110-112' > /etc/permlens/schreiben-erlaubt
```

Alle anderen Container bleiben nur lesbar. Datei löschen, und PermLens liest sofort wieder nur. Mehr dazu: [AENDERN.md](AENDERN.md) und [SICHERHEIT.md, Abschnitt 3](SICHERHEIT.md#3-schreiben-ab-wächter-script-version-4).

## Einstellungen in der Stack-Datei

| Eintrag | Bedeutung |
|---|---|
| `APP_PASSWORD` | **Pflicht**, mindestens 8 Zeichen. In Dockhand als Variable des Stacks, nicht in der Datei selbst. Ohne Passwort zeigt PermLens nur einen Hinweis. Ein neues Passwort meldet alle ab. Passwort vergessen: in Dockhand einen neuen Wert eintragen und den Stack neu starten. |
| `ALLOW_PUBLIC=0` | Nur Zugriffe aus dem Heimnetz (Standard). Nicht ändern. |
| `HTTPS_PORT` | Port, unter dem HTTPS von außen erreichbar ist (`443` oder `8443`). Ist er gesetzt, leitet PermLens unverschlüsselte Aufrufe auf HTTPS um. |
| `HTTPS=0` | Schaltet HTTPS ab. Nur, wenn ein eigener Proxy davor die Verschlüsselung übernimmt (auf eigene Verantwortung, siehe [SICHERHEIT.md, Abschnitt 6](SICHERHEIT.md#6-grenzen-die-du-kennen-solltest)). |
| `TZ=Europe/Berlin` | Zeitzone für die Anzeige. |
| `UPDATE_CHECK=0` | Schaltet den Hinweis „Neue Version verfügbar“ ganz ab. PermLens fragt dann nie bei GitHub nach. Ohne diesen Eintrag lässt er sich unter *Einstellungen → Updates* ein- und ausschalten. |

**Feste Version statt `:latest`:** Wer Updates selbst steuern will, trägt in der Stack-Datei z. B. `ghcr.io/luro611/permlens:1.0.0` ein und ändert die Nummer bei jedem Update.

## Wenn etwas nicht klappt

| Was du siehst | Was hilft |
|---|---|
| Die Seite lädt nicht | Läuft der Container? `docker ps` und `docker logs permlens` im LXC. Stimmt die Adresse und der Port (`8443` mit `https://`)? |
| PermLens zeigt nur einen Hinweis zum Passwort | `APP_PASSWORD` fehlt oder ist kürzer als 8 Zeichen. In Dockhand bei den Variablen des Stacks eintragen, *Redeploy*. |
| „Befehl abgelaufen oder unterwegs verändert, nichts ausgeführt.“ | Der Einmal-Code ist älter als eine Stunde oder schon benutzt. Seite in PermLens neu laden und den neuen Befehl nehmen. |
| „Bitte als root ausführen“ | Die Shell über die Proxmox-Weboberfläche öffnen (Knoten → *>_ Shell*), dort ist man root. |
| „Das ist kein Proxmox-Host (pct fehlt).“ | Der Befehl gehört in die Shell des **Proxmox-Knotens**, nicht in die Konsole eines Containers. |
| „Ungültige Adresse“ | PermLens über die IP-Adresse oder einen einfachen Namen öffnen (nicht über einen Proxy) und den Befehl neu holen. |
| „Der Proxmox antwortet nicht“ | Erreicht der PermLens-LXC den Proxmox auf dem SSH-Port? Läuft eine Firewall dazwischen? Hat der LXC noch die IP-Adresse, mit der er eingerichtet wurde? Sonst *Einstellungen → Neu einrichten*. |

## Wie geht es weiter?

- [Anleitung](ANLEITUNG.md): die Oberfläche und die vier Aufgaben Schritt für Schritt.
- [Betrieb](BETRIEB.md): neue Version einspielen, sichern, entfernen.
- [Sicherheit](SICHERHEIT.md): was PermLens auf dem Proxmox darf, Firewall, Grenzen.
