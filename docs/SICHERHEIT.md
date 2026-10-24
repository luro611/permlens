# Sicherheit: Was PermLens auf deinem Proxmox-Host tut

*English version: [SICHERHEIT.en.md](SICHERHEIT.en.md)*

PermLens braucht Zugriff auf deinen Proxmox-Host. Dieser Abschnitt beschreibt **genau**, was der Einrichtungs-Befehl auf dem Host verändert, was PermLens danach darf und was nicht, und wo die Grenzen liegen. Lies ihn, bevor du den Befehl ausführst.

> **Grundsatz:** Die Sicherheit hängt nicht davon ab, dass PermLens „brav“ ist. Selbst wenn jemand den PermLens-LXC komplett übernimmt (Passwort, Docker, SSH-Schlüssel), darf er auf dem Host nur das, was das Wächter-Script erlaubt. Das Wächter-Script liegt auf dem Host, gehört root und kann von PermLens aus nicht verändert werden.

## 1. Was der Einrichtungs-Befehl auf dem Host macht

Der Befehl, den PermLens anzeigt, sieht so aus (gekürzt):

```
f=$(mktemp) && if curl -fsSL http://<PermLens>/setup/<Einmal-Code> -o "$f" && echo "<Prüfsumme>  $f" | sha256sum -c --status; then bash "$f"; else echo "PermLens: … nichts ausgeführt." >&2; fi; rm -f "$f"
```

Er lädt ein kurzes Bash-Script von PermLens in eine temporäre Datei, vergleicht dessen SHA-256-Prüfsumme mit der Prüfsumme im Befehl und führt es **nur bei Übereinstimmung** als root aus. Danach wird die Datei gelöscht. Ansehen kannst du das Script vorher mit `curl -fsSL http://<PermLens>/setup/<Einmal-Code>`.

Das Script macht genau diese Dinge und sonst nichts:

| Schritt | Was passiert | Welche Datei |
|---|---|---|
| Prüfung | Bricht ab, wenn es nicht als root läuft oder `pct` fehlt (kein Proxmox). | – |
| 1/3 | Lädt das Wächter-Script, prüft seine SHA-256-Prüfsumme (sie steht im geprüften Script) und legt es mit Rechten 755 ab. Eine ältere Version an derselben Stelle wird ersetzt. | `/usr/local/sbin/permlens-guard` (neu) |
| 2/3 | Hängt **eine** Zeile an. Es wird nie eine Zeile gelöscht oder geändert. Steht der Schlüssel schon drin, passiert nichts. | `/root/.ssh/authorized_keys` (eine Zeile mehr) |
| 3/3 | Liest Adresse, SSH-Port, Knotenname und den **öffentlichen** Host-Schlüssel des Proxmox und schickt sie an PermLens zurück. | nur gelesen |

**Das Script tut ausdrücklich nicht:** keine Pakete installieren, keine Dienste neu starten, `sshd_config` nicht ändern, die Proxmox-Firewall nicht ändern, keine Benutzer anlegen, nichts an Cluster, Corosync, Storage, Containern oder VMs ändern, keine API-Tokens anlegen, keine Passwörter lesen oder übertragen.

Die eingetragene Zeile sieht so aus:

```
command="/usr/local/sbin/permlens-guard",restrict,from="192.168.1.50" ssh-ed25519 AAAA… permlens
```

- `command=…` – egal welchen Befehl PermLens schickt, SSH startet **immer** nur das Wächter-Script. Eine Shell gibt es nicht.
- `restrict` – keine Weiterleitungen (Ports, Agent, X11), kein Terminal, keine `~/.ssh/rc`.
- `from=…` – der Schlüssel gilt nur von der Adresse des PermLens-LXC aus. Ein gestohlener Schlüssel nützt von einem anderen Rechner aus nichts.

Der Einmal-Code gilt eine Stunde und nur für eine Einrichtung. Ohne gültigen Code liefert PermLens kein Script aus.

## 2. Was PermLens danach auf dem Host darf

Das Wächter-Script vergleicht jeden Befehl mit einer festen Erlaubnisliste. Was nicht exakt passt, wird abgelehnt (Rückgabewert 126). Befehle werden ohne Shell gestartet, Sonderzeichen wie `;`, `|`, `$( )` haben also keine Wirkung. Jeder Aufruf, erlaubt oder abgelehnt, steht im Systemprotokoll: `journalctl -t permlens`.

**Lesend erlaubt (immer), Wächter-Script Version 7:**

| Auf dem Host | Im Container (über `pct exec <Nr> --`) |
|---|---|
| `pct list`, `pct status <Nr>`, `pct config <Nr>` | `getent passwd`, `getent group` |
| `pvesh get /cluster/resources --type vm` (Liste der Gäste) | `findmnt` (eingehängte Ordner) |
| `cat` von genau drei Dateien: `/etc/subuid`, `/etc/subgid`, `/etc/pve/storage.cfg` | `testparm -s` (Samba-Einstellungen) |
| `getent passwd`, `getent group`, `findmnt` | `stat` für Pfade |
| `stat` und ACLs (nur Besitzer und Rechte, **nicht** der Inhalt), und zwar **nur** für Ordner, die in einem Container als Bind-Mount eingetragen sind (`mpN: /pfad,…` oder `lxc.mount.entry: /pfad …` in `/etc/pve/lxc/<Nr>.conf`) | `cat /etc/exports` (NFS-Freigaben des Containers, neu in Version 3), `getfacl -cpn <Pfad>` (ACL eines Pfads im Container, neu in Version 5) |
| | **Gegenprobe** (neu in Version 3): `setpriv --reuid=<Nr> --regid=<Nr> --clear-groups` bzw. `--groups=<Nr>,…` `-- test -r`, `-w` oder `-x <Pfad>`. Fragt das System als dieser Benutzer, ob Lesen, Schreiben oder Hineingehen erlaubt ist. `test` schreibt nichts, und `setpriv` gibt Rechte nur ab, nie dazu. Andere Programme als `test` und andere Prüfungen als `-r`, `-w`, `-x` lehnt der Wächter ab. |

**Was sich mit Version 3 geändert hat:** Version 2 kannte auf dem Host nur Quellen aus `mpN`-Zeilen. Version 3 erkennt auch Quellen aus `lxc.mount.entry`-Zeilen, im Container zusätzlich `cat /etc/exports` und die Gegenprobe. Alles davon liest nur. Version 4 bringt die ersten schreibenden Befehle (Abschnitt 3); am Lesen ändert sich nichts. Ältere Versionen funktionieren weiter, PermLens zeigt dann einen Hinweis auf der Einstellungsseite. Aktualisieren: Einstellungen → „Neu einrichten“, den Befehl im Proxmox-Terminal ausführen.

Für alle anderen Pfade des Hosts (z. B. `/root`, `/etc/pve/priv`) gibt der Wächter keine Auskunft. Er liest die Container-Konfigurationen bei jeder Anfrage selbst, PermLens kann ihm also keine Pfade „unterschieben“.

Ohne Schalter-Datei (Abschnitt 3) kann PermLens damit **keine** Datei auf dem Host oder in einem Container verändern, keinen Container starten oder stoppen, keine Passwortdateien lesen (`/etc/shadow`, `/etc/pve/priv/…` sind nicht in der Liste) und keine Befehle frei wählen. Der Verbindungstest prüft das bei jeder Einrichtung: Er schickt absichtlich den nicht erlaubten Befehl `id` und meldet einen Fehler, wenn der Wächter ihn nicht ablehnt.

## 3. Schreiben (ab Wächter-Script Version 4)

**Schreibend erlaubt, Wächter-Script Version 7** (nur im Container, nur für freigegebene Container):

| Befehl im Container (über `pct exec <Nr> --`) | Prüfung durch den Wächter |
|---|---|
| `groupadd -g <GID> <Name>` (Gruppe anlegen) | GID nur 1000 bis 59999, Name nur `a-z0-9_-` (am Anfang Buchstabe oder `_`, höchstens 32 Zeichen), keine weiteren Schalter |
| `groupdel <Name>` (Gruppe löschen) | wie oben; zusätzlich fragt der Wächter **selbst** im Container nach (`getent group <Name>`) und lehnt ab, wenn die Gruppe eine Nummer unter 1000 hat (Systemgruppe) |
| `chown <UID>:<GID> <Pfad>` (Besitzer, neu in Version 5) | nur Nummern von 0 bis 60000 (nie `nobody`), genau ein Pfad, nicht rekursiv |
| `chmod <Zahl> <Pfad>` (Rechte, neu in Version 5) | nur oktal (z. B. `2775`, `0755`), **nie setuid** (`4…`), genau ein Pfad, nicht rekursiv |
| `setfacl -m u:<Nr>:rwx <Pfad>`, `setfacl -m g:<Nr>:r-x <Pfad>`, `setfacl -x u:<Nr> <Pfad>`, `setfacl -b <Pfad>` (ACL, neu in Version 5) | genau ein Eintrag für eine Benutzer- oder Gruppennummer, keine Standard-ACL, nicht rekursiv; `-b` entfernt alle ACL-Einträge eines Pfads (PermLens nutzt es, wenn der letzte eigene Eintrag wegfällt, damit wirklich der Zustand ohne ACL zurückkommt) |
| `useradd -m -u <UID> -g <GID> <Name>` (Benutzer anlegen, neu in Version 6) | UID und GID nur 1000 bis 59999, Name wie bei Gruppen, keine weiteren Schalter (also z. B. kein `-o`, keine eigene Shell) |
| `userdel <Name>` (Benutzer löschen, neu in Version 6) | ohne `-r`: der Home-Ordner bleibt immer erhalten; der Wächter fragt vorher im Container nach (`getent passwd`), Benutzer unter 1000 lehnt er ab |
| `usermod -aG <Gruppe> <Name>`, `gpasswd -d <Name> <Gruppe>` (Mitgliedschaft, neu in Version 6) | genau eine Gruppe; der Wächter prüft im Container Benutzer **und** Gruppe nach und lehnt alles unter Nummer 1000 ab. So kann niemand über PermLens in `sudo`, `root` oder eine andere Systemgruppe kommen |
| `usermod -g <GID> <Name>` (Hauptgruppe, neu in Version 6) | GID 1000 bis 59999, Benutzer ab 1000 (im Container nachgeprüft) |
| `usermod -u <UID> <Name>`, `groupmod -g <GID> <Name>` (Nummer ändern, neu in Version 7) | neue Nummer 1000 bis 59999; Benutzer bzw. Gruppe ab 1000, im Container nachgeprüft |
| `find <Ordner> -xdev -user <alt> -exec chown -h <neu> {} +` bzw. `-group … -exec chgrp -h …` (Dateien umnummerieren, neu in Version 7) | genau diese Form: bleibt auf einem Dateisystem (`-xdev`), ändert symbolische Verknüpfungen selbst statt ihres Ziels (`-h`), nichts anderes als `chown`/`chgrp` |
| `chown -R -h <UID>:<GID> <Ordner>`, `chmod -R <Rechte> <Ordner>`, `setfacl -R [-d] -m …`, `setfacl -R -x …` (rekursiv, neu in Version 7) | wie die einzelnen Befehle; `chmod -R` auch symbolisch (z. B. `g+rwX,o-rwx`), aber ohne `s` (rekursiv träfe setgid auch Dateien), setuid nie |
| `getfacl -R -p -n -P <Ordner>` (Sicherung) und `find <Ordner> -xdev [-user|-group <Nr>] -printf .` (Zählen) | nur in freigegebenen Containern, weil sie die Ordner durchsuchen; das Zählen liefert nur Punkte, keine Dateinamen |
| `permlens-restore <Ordner>` (Sicherung zurückspielen, neu in Version 7) | kein echtes Programm: Der Wächter liest die Sicherung von der Standard-Eingabe, prüft **jeden** Pfad darin (muss unter dem Ordner liegen, auch in Oktal-Schreibweise versteckte `..` zählen nicht) und lehnt Sicherungen ab, die setuid setzen würden. Erst dann gibt er sie an `setfacl --physical --restore=-` weiter |
| Schreibtest (neu in Version 5): `setpriv --reuid=<Nr> --regid=<Nr> … -- touch <Ordner>/.permlens-schreibtest-<12 Zeichen>` und `rm -f` derselben Datei (als dieser Benutzer oder als root) | nur genau dieser Dateiname, sonst nichts anlegen oder löschen |

**Wo PermLens ändern darf (ab Version 5):** Besitzer, Rechte, ACL, Umnummerieren, Sicherung, Wiederherstellen und der Schreibtest gehen nur in den **eingehängten Ordnern** des Containers (Ziele aus `mpN: …,mp=/ziel` und `lxc.mount.entry` in `/etc/pve/lxc/<Nr>.conf`, die der Wächter selbst liest) und darunter, sowie unter `/home`. Systemordner wie `/etc`, `/usr` oder `/` sind nie erlaubt. Vor jedem dieser Befehle prüft der Wächter im Container mit `realpath -e`, dass der Pfad existiert und **keine symbolische Verknüpfung** enthält. So kann eine Verknüpfung in einem Ordner (z. B. auf `/etc/shadow`) nicht ausgenutzt werden.

Passwörter setzt PermLens nie (kein `passwd`, kein `chpasswd`).

**Rekursive Änderungen (ab Version 7):** Vorher sichert PermLens Besitzer, Rechte und ACLs **aller** Dateien darunter mit `getfacl -R` und speichert die Sicherung in seiner Datenbank. Klappt die Sicherung nicht, wird nichts geändert. „Rückgängig“ spielt genau diese Sicherung zurück. Höchstens 200 000 Dateien auf einmal. Grenze: Den Besitzer symbolischer Verknüpfungen selbst hält die Sicherung nicht fest.

Für alle Schreibbefehle gelten diese Regeln:

- Sie funktionieren nur, wenn auf dem Host die Datei `/etc/permlens/schreiben-erlaubt` existiert **und** der Container darin steht. Diese Datei legst **du** von Hand an (`mkdir -p /etc/permlens && echo '9001-9006' > /etc/permlens/schreiben-erlaubt`) und kannst sie jederzeit löschen oder leeren. Danach ist PermLens sofort wieder nur lesend. PermLens selbst kann diese Datei nicht anlegen. Der Wächter liest sie bei jedem Befehl neu.
- **In der Datei steht, welche Container PermLens ändern darf**, Nummern und Bereiche, getrennt durch Zeilenumbruch, Komma oder Leerzeichen, z. B. `9001-9006` oder `140,150-152`. Alle anderen Container bleiben auch mit Schalter-Datei nur lesbar. Eine leere Datei erlaubt **nichts**. So kann man zuerst nur an Test-Containern üben und später einzelne echte Container gezielt freigeben.
- Die Datei liegt bewusst **nicht** in `/etc/pve`, sie gilt also nur für diesen einen Knoten, nicht für den ganzen Cluster.
- Auch dann gibt es keine freien Befehle, sondern nur einzeln erlaubte, deren Werte streng geprüft werden (z. B. Benutzername nur aus `a-z0-9_-`, UID nur als Zahl). root und Systemkonten (Nummern unter 1000) ändert PermLens nie.
- Jeder Schreibbefehl steht mit `SCHREIBEN:` im Systemprotokoll (`journalctl -t permlens`), abgelehnte mit `ABGELEHNT`.
- In PermLens selbst: Vor jeder Änderung zeigt eine Vorschau den genauen Befehl, eine Einstufung (harmlos, Vorsicht, Risiko), den Zustand vorher und nachher und den Befehl zum Rückgängigmachen. Bei „Risiko“ muss zusätzlich die Container-Nummer eingetippt werden. Jede Änderung steht auf der Seite „Änderungen“ und lässt sich dort rückgängig machen.
- Benutzer anlegen, `chown`, `chmod` und ACLs laufen **im Container** über `pct exec`. Sie ändern nur das Dateisystem dieses Containers bzw. die eingehängten Ordner, nicht das Host-System.
- Änderungen an der Host-Konfiguration (idmap in `/etc/pve/lxc/<Nr>.conf`, `/etc/subuid`, `/etc/subgid`) sind eine eigene, gefährlichere Stufe. PermLens zeigt dafür bisher nur die Befehle (Mapping-Assistent), selbst ausführen ist für nach Version 1.0 geplant.

## 4. Proxmox-Cluster: Das musst du wissen

- **`/root/.ssh/authorized_keys` gilt für den ganzen Cluster.** Bei Proxmox ist die Datei ein Link auf `/etc/pve/priv/authorized_keys`, und `/etc/pve` wird auf alle Knoten verteilt. Die PermLens-Zeile steht damit auf **allen** Knoten.
- Das ist trotzdem sicher: Das Wächter-Script wird nur auf dem Knoten installiert, auf dem du den Befehl ausführst. Auf den anderen Knoten fehlt es, und SSH bricht die Anmeldung mit dem PermLens-Schlüssel dort ab (es gibt keine Ausweich-Shell).
- Über diese Datei sprechen auch die Cluster-Knoten miteinander (Migration, Replikation, Konsole). PermLens hängt nur an und lässt alle anderen Zeilen unberührt. **Wenn du die Zeile von Hand entfernst, lösche nur die Zeile mit `permlens` am Ende.** Eine falsch gelöschte Zeile kann Migrationen und die Konsole zwischen den Knoten stören.
- Hat der Cluster kein Quorum, ist `/etc/pve` schreibgeschützt. Das Script bricht dann mit einem Fehler ab und hat nichts verändert (das Wächter-Script ist dann aber schon abgelegt, das schadet nicht).
- `pvesh get /cluster/resources` zeigt die Gäste aller Knoten an (nur lesen). Container-Details (`pct config`, `pct exec`) gibt es nur für Container auf dem verbundenen Knoten.
- Weder Corosync noch HA, Storage-Einstellungen, Firewall oder Zertifikate werden angefasst.

## 4a. Mehrere Proxmox (ab PermLens 0.5.0)

- PermLens kann mit mehreren Proxmox verbunden sein (z. B. zu Hause und auf der Arbeit). Auf jedem führst du den Einrichtungs-Befehl einmal aus. Jeder bekommt dabei sein eigenes Wächter-Script und seine eigene Zeile in `authorized_keys`, mit demselben Schlüssel von PermLens.
- **Ob PermLens ändern darf, entscheidet jeder Proxmox für sich** mit seiner eigenen Datei `/etc/permlens/schreiben-erlaubt`. Ein Proxmox ohne diese Datei bleibt nur lesend, auch wenn ein anderer das Schreiben erlaubt.
- PermLens zeigt immer an, welcher Proxmox gerade gewählt ist (unter der Kopfzeile), und nennt ihn in jeder Vorschau. Eine Vorschau gilt nur für den Proxmox, für den sie erstellt wurde: Schaltest du zwischendurch um (z. B. in einem anderen Tab), führt PermLens sie nicht aus.
- „Aus PermLens entfernen“ (Einstellungen → Proxmox) löscht nur den Eintrag in PermLens. Den Zugang auf dem Proxmox selbst entfernst du wie in Abschnitt 9 beschrieben.
- Wird PermLens übernommen, kann ein Angreifer auf **jedem** verbundenen Proxmox das tun, was dessen Wächter erlaubt. Verbinde deshalb nur Proxmox, denen du PermLens anvertraust, und schalte das Schreiben nur dort frei, wo du es brauchst.

## 4b. Zwei-Faktor-Anmeldung (ab PermLens 0.5.2)

Wahlweise unter **Einstellungen → Zwei-Faktor-Anmeldung**. Dann reicht das Passwort allein nicht mehr: Nach dem Passwort fragt PermLens nach einem sechsstelligen Code aus einer Authenticator-App (OTP Auth, Aegis, 2FAS, Google Authenticator …). Das Verfahren ist TOTP nach RFC 6238, wie bei Nextcloud.

- **Einrichten:** QR-Code scannen, dann einen Code aus der App eingeben. Erst damit ist es eingeschaltet. So sperrst du dich nicht aus, wenn das Scannen schiefgeht.
- **Der geheime Schlüssel** liegt nur im PermLens-LXC in `/opt/permlens/data/totp.json` (Rechte 600), nie auf dem Proxmox. Wer den LXC übernimmt, hat auch diesen Schlüssel. Die Zwei-Faktor-Anmeldung schützt also vor einem bekannt gewordenen Passwort, nicht vor einem übernommenen LXC.
- **Ein Code gilt nur einmal** und etwa 30 Sekunden (eine halbe Minute Abweichung der Uhr in jede Richtung ist erlaubt). Fehlversuche zählen wie beim Passwort: nach 5 Fehlversuchen 5 Minuten Sperre.
- **Zwischen Passwort und Code** hast du 5 Minuten. Das Cookie dafür gilt nicht als Anmeldung.
- **Gültigkeit (ab 0.5.4):** Die Anmeldung endet, wenn du den Browser schließt. Danach ist immer das Passwort fällig. Den Code aus der App gibst du **einmal am Tag je Browser** ein: Ein eigenes Cookie merkt sich bis 24:00 Uhr (Zeitzone `TZ` des Containers), dass der Code eingegeben wurde. Um Mitternacht endet auch eine noch offene Anmeldung, danach braucht es Passwort und neuen Code. „Abmelden“ löscht beide Cookies. Das Tages-Cookie allein meldet niemanden an, das Passwort braucht es immer.
- Hinweis: Manche Browser stellen beim Neustart die letzte Sitzung samt Cookies wieder her (z. B. „Beim Start: dort weitermachen, wo ich aufgehört habe“). Dann bleibt man auch nach dem Schließen angemeldet. Wer das nicht will, nutzt „Abmelden“.
- **Ersatz-Codes:** Beim Einschalten zeigt PermLens einmal zehn Ersatz-Codes. Jeder ersetzt einmal den Code aus der App. Gespeichert werden nur ihre Prüfsummen.
- **Ein- und Ausschalten meldet alle anderen Browser ab.** Ausschalten und neue Ersatz-Codes brauchen den aktuellen Code aus der App.
- **Handy weg, keine Ersatz-Codes mehr:** Im PermLens-LXC `rm /opt/permlens/data/totp.json` ausführen. Danach reicht wieder das Passwort. Wer das kann, hat ohnehin vollen Zugriff auf den LXC.
- Jeder Schritt steht im Protokoll (`login` mit `zweiter_faktor`, `zwei-faktor`).

## 4c. Hinweis „Neue Version verfügbar“ (ab PermLens 0.5.7)

- PermLens fragt kurz nach dem Start und danach alle sechs Stunden `https://api.github.com/repos/luro611/permlens/releases/latest` ab. Das ist die öffentliche Liste der Releases, ohne Anmeldung.
- **Mitgeschickt wird nur** die eigene Versionsnummer im User-Agent (`PermLens/0.5.7 …`). Keine Daten vom Proxmox, keine Kennung, kein Passwort. GitHub sieht wie bei jedem Aufruf die Adresse deines Internet-Anschlusses.
- Gibt es eine neuere Version, steht unten auf jeder Seite ein Link zum Release. **Eingespielt wird nichts von selbst**, das machst du in Dockhand (Pull und Redeploy).
- **Abschalten:** Einstellungen → Updates, Häkchen weg. Oder ganz aus mit `UPDATE_CHECK=0` bei `environment` in der Stack-Datei. Dann fragt PermLens GitHub nie, auch nicht kurz nach dem Start.
- Ein- und Ausschalten steht im Protokoll (`update-hinweis`).

## 5. Wie das Image von PermLens gebaut ist

Auch die Software selbst soll nachvollziehbar sein (ab Version 0.2.1):

| Was | Wie |
|---|---|
| **Python-Pakete** | Jede Version ist fest angegeben und mit SHA-256-Prüfsumme versehen (`requirements.txt`). Beim Bauen nimmt `pip --require-hashes` nur genau diese Dateien. Ein ausgetauschtes Paket auf PyPI würde den Bau abbrechen. |
| **Basis-Image** | `python:3.12-slim` ist nicht nur per Name, sondern per Digest (`@sha256:…`) festgelegt. Updates erfolgen bewusst: neuen Digest eintragen, bauen, testen. |
| **Kein root** | PermLens läuft im Container als eigener Benutzer `permlens` (UID 10001), ohne Sonderrechte (`no_new_privs`, keine Capabilities). Nur beim Start übernimmt ein kleines Script einmal den Daten-Ordner, falls er noch root gehört (Daten aus älteren Versionen), und gibt dann alle Rechte ab. Den Programmcode kann PermLens selbst nicht verändern. |
| **Kein Docker-Socket** | Der PermLens-Container hat keinen Zugriff auf Docker. |
| **SBOM und Herkunftsnachweis** | Jedes Image trägt eine Liste aller enthaltenen Pakete (SBOM) und einen Nachweis, aus welchem Commit es gebaut wurde. Ansehen: `docker buildx imagetools inspect ghcr.io/luro611/permlens:<Version> --format '{{ json .SBOM }}'` |
| **Kein automatischer Bau in der Cloud** | Das Image wird von Hand gebaut (`tools/publish.sh`), nur von einem Stand, der auf GitHub liegt. Es gibt keine GitHub Actions und damit keine Runner, die Zugangsdaten sehen könnten. |

Nicht fest angegeben sind die beiden Debian-Pakete `openssh-client` und `tzdata`: Sie kommen beim Bauen mit den aktuellen Sicherheitsupdates von Debian.

**Wer selbst bestimmen will, wann eine neue Version kommt,** trägt in der Stack-Datei statt `:latest` eine feste Version ein, z. B. `ghcr.io/luro611/permlens:0.2.1`, und ändert sie bei jedem Update selbst.

## 6. Grenzen, die du kennen solltest

Ehrlich gesagt gibt es Stellen, an denen PermLens dir und deinem Heimnetz vertrauen muss:

1. **HTTPS mit eigenem Zertifikat (ab 0.2.2).** PermLens verschlüsselt mit einem selbst erzeugten Zertifikat. Der Browser warnt einmal, den Fingerabdruck kannst du prüfen (siehe [BETRIEB.md](BETRIEB.md)). Der Einrichtungs-Befehl legt den Schlüssel des Zertifikats fest (`--pinnedpubkey`): Ein Gerät, das sich zwischen Proxmox und PermLens schiebt, bekommt die Verbindung gar nicht erst zustande. Zusätzlich prüft der Befehl wie bisher die SHA-256-Prüfsumme des Scripts. Wer HTTPS abschaltet (`HTTPS=0`) oder PermLens über `http://` aufruft, verliert den ersten Schutz. Dann bleibt nur die Prüfsumme, die über deinen Browser kommt.
2. **Wer PermLens hat, hat die Rechte des Wächters.** Wer das PermLens-Passwort kennt oder den LXC übernimmt, kann alles, was die Erlaubnisliste zulässt: ohne Schalter-Datei nur lesen, mit ihr die Änderungen aus Abschnitt 3 in den freigegebenen Containern. Deshalb: starkes `APP_PASSWORD`, am besten die Zwei-Faktor-Anmeldung einschalten (Abschnitt 4b), PermLens nie ins Internet, den LXC aktuell halten.
3. **Lesen verrät etwas über das System.** PermLens sieht Benutzerlisten, Mounts, Speicherkonfiguration und die Rechte der eingehängten Ordner (nicht deren Inhalt). Das ist der Zweck des Programms, aber gut zu wissen.
4. **`pct exec` führt Programme aus dem Container aus.** `getent`, `stat` usw. stammen aus dem Container. Ein manipulierter Container könnte PermLens falsche Angaben liefern. Er bekommt dadurch aber nicht mehr Rechte, als er ohnehin hat.
5. **Eine schon vorhandene Zeile bleibt, wie sie ist.** Hast du den PermLens-Schlüssel früher einmal ohne Einschränkung eingetragen, ändert das Script das nicht. Der Verbindungstest erkennt das („Wächter lehnt fremde Befehle ab“ schlägt fehl). Dann die alte Zeile löschen und neu einrichten.

## 7. Empfohlen: Firewall für den PermLens-LXC

PermLens braucht von außen nur die Weboberfläche, und nach außen nur SSH zum Proxmox (dazu, wenn eingeschaltet, HTTPS zu `api.github.com` für den Update-Hinweis, Abschnitt 4c). Mit der Firewall von Proxmox lässt sich das erzwingen. Selbst ein übernommener PermLens-LXC kommt dann nicht an andere Geräte im Heimnetz.

**Vorsicht:** Die Firewall von Proxmox wirkt nur, wenn sie unter *Rechenzentrum → Firewall → Optionen* eingeschaltet ist. Dann gilt sie auch für den Host. Proxmox lässt dabei Weboberfläche (8006) und SSH aus dem lokalen Netz weiter zu. Prüfe trotzdem vorher, dass du notfalls an die Konsole des Proxmox kommst.

So geht es in der Proxmox-Oberfläche beim PermLens-LXC:

1. *Netzwerk* → `net0` bearbeiten → **Firewall** anhaken.
2. *Firewall → Optionen*: **Firewall: Ja**, **Eingangsrichtlinie: DROP**, Ausgangsrichtlinie vorerst **ACCEPT**.
3. *Firewall → Regeln*, eingehend (**in**, Aktion **ACCEPT**, Protokoll **tcp**):

   | Ziel-Port | Quelle | Wofür |
   |---|---|---|
   | `443` (bzw. `8443`) und `80` (bzw. `8000`) | dein Heimnetz, z. B. `192.168.1.0/24` | Weboberfläche von PermLens |
   | Port von Hawser (in Dockhand bei der Umgebung ablesen, meist `2376`) | nur die IP des Dockhand-LXC | Verwaltung über Dockhand (Hawser im Standard-Modus) |

4. Optional strenger, Ausgangsrichtlinie **DROP** mit diesen Ausnahmen (**out**, **ACCEPT**): `tcp 22` nur zur IP des Proxmox (PermLens), `udp/tcp 53` zum DNS-Server, `tcp 443` und `tcp 80` (Image- und Paket-Updates, Update-Hinweis). Das ist sicherer, aber jedes neue Ziel muss dann freigegeben werden.

Prüfen: Die Weboberfläche geht weiter, *Verbindung testen* in PermLens geht weiter, und von einem anderen Rechner im Netz antwortet der LXC auf keinen anderen Port, z. B. mit `nmap <IP-des-LXC>`.

**Hawser und Dockhand:** Wer Dockhand bedienen kann, kann über Hawser auch den PermLens-Container steuern und damit seinen SSH-Schlüssel benutzen. Schütze deinen Dockhand-Zugang deshalb mindestens so gut wie PermLens selbst: starkes Passwort, und die Zwei-Faktor-Anmeldung, falls deine Dockhand-Version sie anbietet.

## 8. Selbst nachprüfen

```bash
grep permlens /root/.ssh/authorized_keys
```

```bash
journalctl -t permlens --since today
```

```bash
sha256sum /usr/local/sbin/permlens-guard
```

Die erste Zeile muss mit `command="/usr/local/sbin/permlens-guard",restrict,from="…"` beginnen. Im Protokoll sollten nur Einträge mit `erlaubt:` stehen, außer dem einen `ABGELEHNT: id` vom Verbindungstest. Einträge mit `SCHREIBEN:` gibt es nur, wenn du das Schreiben freigegeben hast; jeder davon muss zu einer Zeile auf der Seite „Änderungen“ in PermLens passen.

## 9. Vollständig entfernen

Auf dem Knoten, auf dem du PermLens eingerichtet hast (bei mehreren Proxmox auf jedem):

```bash
cp /root/.ssh/authorized_keys /root/authorized_keys.vor-permlens
```

```bash
grep -v ' permlens$' /root/authorized_keys.vor-permlens > /root/.ssh/authorized_keys
```

```bash
rm -f /usr/local/sbin/permlens-guard && rm -rf /etc/permlens
```

Der erste Befehl legt eine Sicherung an, der zweite schreibt die Datei ohne die Zeilen zurück, die auf ` permlens` enden. Der Link nach `/etc/pve/priv/` bleibt dabei erhalten. **Nicht** `sed -i` verwenden: Das ersetzt den Link durch eine normale Datei, und im Cluster stimmen die Schlüssel dann nicht mehr. Im Cluster reicht es, die beiden ersten Befehle auf einem Knoten auszuführen. Danach hat PermLens keinerlei Zugang mehr.
