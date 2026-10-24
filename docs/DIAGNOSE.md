# Prüfen und Probleme: Warum darf jemand (nicht) schreiben?

*English version: [DIAGNOSE.en.md](DIAGNOSE.en.md)*

PermLens beantwortet die Frage **„Kann Benutzer X im Container Y den Ordner Z lesen oder beschreiben, und wenn nicht, warum?“** Es erklärt jeden Schritt in Klartext und sagt, was du tun kannst.

Prüfen selbst **ändert nichts**. Alle Befehle in den Empfehlungen sind zum Kopieren gedacht. Hast du das Ändern auf dem Proxmox für einen Container freigegeben, kann PermLens viele Empfehlungen auch selbst ausführen, immer erst mit Vorschau: siehe **[AENDERN.md](AENDERN.md)**. Einen Rundgang durch alle Seiten gibt die **[Anleitung](ANLEITUNG.md)**.

## Das Wichtigste vorab: Es zählt die Nummer, nicht der Name

Linux merkt sich bei jeder Datei nicht den Namen des Besitzers, sondern eine **Nummer** (UID für den Benutzer, GID für die Gruppe). Der Name ist nur eine Übersetzung, und die kann überall anders sein:

| Wo | „luro“ hat zum Beispiel |
|---|---|
| Mac (erster Benutzer) | UID 501 |
| Linux-PC, Container | UID 1000 |
| Proxmox-Host | vielleicht UID 1001, und 1000 heißt dort ganz anders |
| Unprivilegierter Container, von außen gesehen | UID 101000 |

Gleicher Name heißt also nicht gleicher Benutzer. Genau daher kommen die meisten Rechte-Probleme.

**Privilegiert oder unprivilegiert?**

- **Privilegierter Container:** Die Nummern sind innen und außen gleich. root im Container ist root auf dem Host. Das ist bequem, schottet den Container aber schwächer ab.
- **Unprivilegierter Container:** Proxmox verschiebt alle Nummern um 100000. Aus 1000 im Container wird 101000 auf dem Host. Ein Ordner, der auf dem Host 1000 gehört, gehört im Container deshalb **nobody** (65534).
- **Eigenes Mapping** (`lxc.idmap`): Bestimmte Nummern werden 1:1 durchgereicht, der Rest wird verschoben.

## Wo du was findest

| Seite | Wofür |
|---|---|
| **Übersicht** | Die drei wichtigsten Probleme, darunter alle Container und VMs |
| **Probleme** | Alles, was PermLens beim Einlesen von selbst gefunden hat, mit Empfehlung (Abschnitt „Befunde“ unten) |
| **Prüfen** | Die Frage „Kann wer hier schreiben?“ |
| **Ordner** | Jeder eingehängte Ordner mit Besitzer und wie er aus jedem Container aussieht. Weitere Reiter: Namen und Nummern im Vergleich, Speicher des Hosts mit `/etc/subuid` und `/etc/subgid`. |
| **Container** (Klick in der Übersicht) | Reiter Überblick, Benutzer und Gruppen, Ordner (mit Freigaben bei Samba- oder NFS-Servern) und Host-Einstellungen |

## Die Seite „Prüfen“

1. **Container wählen:** Nur laufende Container lassen sich prüfen, denn nur dort gibt es eine Benutzerliste.
2. **Benutzer wählen:** Zuerst kommen die normalen Benutzer, darunter die Systembenutzer (zum Beispiel `www-data`).
3. **Ordner wählen:** Die eingehängten Ordner stehen als Knöpfe bereit. Du kannst auch einen eigenen Pfad eintippen, PermLens liest ihn dann frisch aus dem Container.

Prüfen kannst du auch direkt von der Container-Seite: Reiter Ordner, Knopf „Prüfen“ beim jeweiligen Ordner.

Du bekommst, von oben nach unten:

- **Lesen ja/nein** und **Schreiben ja/nein**, darunter die Ursache in einem Satz.
- **„So geht es“:** Empfehlungen mit Befehl und Einstufung (siehe unten). Was PermLens selbst ausführen kann, hat einen Knopf „Mit PermLens ausführen …“. Darunter „Selbst ändern: Besitzer, Rechte, ACL“, falls keine Empfehlung passt.
- **„Sicher gehen“** (eingeklappt): die Gegenprobe und der echte Schreibtest (siehe unten).
- **„So hat PermLens gerechnet“** (eingeklappt): jeder Ordner auf dem Weg. Um in einen Ordner hineinzukommen, braucht jeder Ordner davor das Recht `x`. Zum Lesen braucht der Zielordner `r` und `x`, zum Schreiben `w` und `x`.

### So rechnet PermLens

Wie Linux selbst, in dieser Reihenfolge:

1. **root** darf alles. In einem unprivilegierten Container gilt das aber nur für Dateien, deren Besitzer im Container abgebildet ist. Gehört etwas nobody, ist auch root dort nur ein „anderer“.
2. Ist der Benutzer der **Besitzer**, gelten die Rechte des Besitzers.
3. Gibt es eine **ACL für den Benutzer**, gilt sie (begrenzt durch die Maske).
4. Ist der Benutzer in der **Gruppe** des Ordners oder in einer ACL-Gruppe, gelten deren Rechte. Passt eine Gruppe, erlaubt es aber nicht, ist die Antwort nein. Die Rechte für „andere“ zählen dann nicht mehr.
5. Sonst gelten die Rechte für **andere**.

Dazu: Ein schreibgeschützt eingehängter Ordner (`ro=1`) verbietet das Schreiben immer.

### Mögliche Ursachen

| Ursache | Bedeutet |
|---|---|
| **nobody** | Der Besitzer auf dem Host ist im unprivilegierten Container nicht abgebildet. Es gelten nur die Rechte für „andere“. |
| **Weg versperrt** | Ein Ordner davor lässt den Benutzer nicht hinein (`x` fehlt). |
| **Rechte** | Besitzer, Gruppe oder ACL erlauben es diesem Benutzer nicht. |
| **nur lesen** | Der Ordner ist schreibgeschützt eingehängt. |
| **fehlt** | Den Pfad gibt es im Container nicht. |
| **keine Antwort** | Der Ordner antwortet nicht, meist ist das NAS ausgeschaltet. |

### Sicher gehen: Gegenprobe und echter Schreibtest

Bei NFS entscheidet das NAS selbst, und manche NAS haben eigene Rechte-Listen. Dann kann ein Ordner `rwxrwxrwx` zeigen und trotzdem das Schreiben ablehnen. Für solche Fälle gibt es unter „Sicher gehen“ die **„Gegenprobe: das System selbst fragen“**. PermLens fragt dabei im Container **als dieser Benutzer** nach (`setpriv … test -r/-w/-x`), ob es geht, und schreibt dabei nichts.

- **„Passt zur Rechnung“**: Alles stimmt.
- **„Weicht von der Rechnung ab“**: Ein anderes System entscheidet mit, meist das NAS.

**Grenze bei NFS:** Manche NAS antworten auf die Nachfrage anders, als sie beim echten Schreiben entscheiden. Im Test mit einer UGREEN meldete die Gegenprobe „Lesen nein, Schreiben ja“, das echte Schreiben scheiterte trotzdem. Bei NFS ist die Gegenprobe deshalb ein Hinweis, dass das NAS anders entscheidet, aber keine Garantie. Sicher ist nur ein echter Schreibversuch.

Die Gegenprobe braucht das Wächter-Script ab Version 3. Jede Gegenprobe steht im Protokoll von PermLens.

**Echter Schreibtest:** Ist Ändern für den Container freigegeben, legt PermLens als dieser Benutzer eine kleine Testdatei an und löscht sie gleich wieder. Das Ergebnis heißt dann „Schreiben klappt wirklich“ oder „klappt wirklich nicht“. Das ist die sichere Antwort, auch bei NFS. Details: [AENDERN.md](AENDERN.md).

## Die Seite „Probleme“: Befunde

Nach jedem Einlesen prüft PermLens von selbst bekannte Fehlerquellen. Die drei wichtigsten stehen oben auf der Übersicht, alle auf der Seite **Probleme**, die eines Containers in seinem Reiter Überblick. Viele haben einen Knopf „Mit PermLens ausführen …“, einen Link „Zum Container“ oder „Im Mapping-Assistenten genau planen“. Jeder Befund hat eine Stufe:

- **Problem:** Etwas funktioniert nicht.
- **Hinweis:** Es funktioniert, ist aber riskant oder wackelig.
- **Info:** Gut zu wissen, kein Handlungsbedarf.

| Befund | Stufe | Was dahintersteckt |
|---|---|---|
| Mount-Quelle fehlt | Problem | Ein Container soll einen Host-Ordner einhängen, den es nicht gibt. Der Container startet dann nicht oder sieht nur einen leeren Ordner. Oft ist das ein alter Eintrag. |
| Container sieht einen Ordner als nobody | Problem | Unprivilegierter Container, Besitzer nicht abgebildet |
| App kann nicht in … schreiben | Problem | Eine Docker-App läuft als eine Nummer, die in ihrem Ordner nicht schreiben darf. Meist passt `PUID`/`PGID` nicht zum Besitzer des Ordners. |
| Privilegierter Container mit Host-Ordnern | Hinweis | Bequem, aber schwächer abgeschottet |
| Gemeinsamer Ordner ohne setgid | Hinweis | Mehrere Container nutzen den Ordner. Neue Dateien bekommen die falsche Gruppe, und die anderen können sie oft nicht ändern. |
| Gleicher Name, verschiedene Nummern | Hinweis | Zum Beispiel `luro` auf dem Host 1001, im Container 1000 |
| NFS-Freigabe mit `no_root_squash` | Hinweis | root vom anderen Gerät bleibt root |
| App schreibt als root | Hinweis | Neue Dateien der App gehören im unprivilegierten Container root, auf dem Proxmox also 100000. Andere Container und der Mac kommen dann oft nicht heran. |
| Gleiche Nummer, verschiedene Namen | Info | Zum Beispiel 1000 heißt auf dem Host `paperless`, im Samba-Container `luro` |
| Samba-Freigabe schreibt immer als … | Info | `force user`: Egal wer sich am Mac anmeldet, alles gehört diesem Benutzer. |
| NFS / SMB | Info | Bei NFS zählt die Nummer, bei SMB die Mount-Optionen (`uid=`, `gid=`) |
| Ungenutzte Einträge in `/etc/subuid` / `/etc/subgid` | Info | Container auf Proxmox nutzen nur die Einträge von root. |
| Keine Antwort | Info | NAS ausgeschaltet, kein Fehler im Container |
| App läuft nicht als `PUID` | Info | `PUID` ist gesetzt, die Programme laufen aber als eine andere Nummer. Nicht jedes Image beachtet diese Variable. |

## Einstufung der Empfehlungen

Jede Empfehlung sagt, **wo** der Befehl hingehört (auf dem Proxmox-Host oder im Container) und **wie riskant** er ist:

| Einstufung | Bedeutet | Beispiele |
|---|---|---|
| **harmlos** | Ändert nichts an bestehenden Rechten | Gruppe anlegen |
| **Vorsicht** | Erweitert oder entzieht Rechte, leicht rückgängig zu machen | `usermod -aG gruppe benutzer`, `chmod g+s ordner`, einen veralteten Mount-Punkt entfernen |
| **Risiko** | Kann Zugriffe kaputt machen oder zu viel öffnen | Mapping ändern (`lxc.idmap`), `chown` auf einem gemeinsamen Ordner, `chmod 777` |

Vor einem Befehl mit **Risiko**: die Container-Einstellung sichern, zum Beispiel mit `cp /etc/pve/lxc/<Nr>.conf /root/<Nr>.conf.vorher`.

## Speicher-Wege: Wer schreibt am Ende wirklich?

| Weg | Beispiel | Was zählt |
|---|---|---|
| Host-Ordner per `mpN` eingehängt | `/mnt/daten` → Container | Besitzer, Rechte, ACL und das Mapping |
| Host-Ordner per `lxc.mount.entry` | wie oben, nur anders eingetragen | wie oben (Host-Rechte ab Wächter 3) |
| NFS-Freigabe über den Host | NAS → `/mnt/pve/…` → Container | Die Nummer, mit der der Container beim NAS ankommt. Das NAS entscheidet. |
| SMB-Freigabe über den Host | NAS → `/mnt/pve/…` → Container | Die Mount-Optionen `uid=`, `gid=`, `file_mode=`. `chown` wirkt nicht. |
| Container hängt selbst NFS/SMB ein | eigene `fstab` im Container | wie NFS bzw. SMB |
| Container ist Samba-Server | Mac → Freigabe → Container | `force user` / `force group`, sonst der angemeldete Samba-Benutzer |
| Container ist NFS-Server | Gerät → `/etc/exports` | `all_squash`/`anonuid`, sonst die Nummer des Geräts |

**Beispiel:** Ein Mac schreibt über eine Samba-Freigabe mit `force user = luro`. Im Samba-Container ist das die Nummer 1000. Der Container ist privilegiert, also ist es auch auf dem Host die 1000. Die UID 501 des Macs spielt keine Rolle.

## Nummern ohne Namen

Viele Dienste laufen in Docker und schreiben unter einer Nummer, für die es im Container keinen Benutzer gibt. paperless-ngx macht das zum Beispiel mit `USERMAP_UID=1000`. Auf der Container-Seite steht dann im Reiter Benutzer und Gruppen unter **„Nummern ohne Namen“**, welche Nummer welchen Ordner besitzt und wie sie woanders heißt. Für die Rechte ist das kein Fehler, es ist nur schwerer zu lesen. Läuft im Container Docker, zeigt ab 1.1.0 der Reiter **Docker**, welche App hinter der Nummer steckt.

## Was PermLens nicht kann

- **Rechte auf einem NAS ändern oder lesen** (Rechte-Listen, Squash-Regeln einer Synology, UGREEN oder TrueNAS). PermLens sagt dir, dass die Lösung dort liegt.
- **Samba-Passwörter und `smb.conf`** verwalten. Das macht ein eigener Fileserver mit Oberfläche.
- **Benutzer auf dem Mac, unter Windows oder auf dem Proxmox-Host** anlegen.
- **In VMs schauen.** VMs erscheinen nur in der Liste.
- **Mapping und Mount-Punkte auf dem Host ändern.** Der Mapping-Assistent zeigt die genauen Befehle ([MAPPING.md](MAPPING.md)), ausführen musst du sie in der Shell des Proxmox. Dass PermLens das selbst kann, ist für nach Version 1.0 geplant. Benutzer, Gruppen und Rechte **im Container** ändert PermLens dagegen schon, wenn du es freigibst ([AENDERN.md](AENDERN.md)).
