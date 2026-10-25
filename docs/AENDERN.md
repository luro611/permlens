# Ändern: Rechte, Benutzer und Gruppen mit PermLens

*English version: [AENDERN.en.md](AENDERN.en.md)*

Ab Version 0.3.0 kann PermLens die Empfehlungen von [Prüfen und Probleme](DIAGNOSE.md) selbst umsetzen: Besitzer, Rechte und ACLs von Ordnern ändern, Benutzer und Gruppen im Container anlegen und ändern, Nummern umstellen und ganze Ordnerbäume anpassen. Jede Aktion steht hier so, wie du sie auch selbst im Terminal des Containers ausführen würdest.

## Das Wichtigste vorab

- **Ausgeschaltet, bis du es auf dem Proxmox einschaltest.** Ohne die Schalter-Datei liest PermLens nur.
- **Nur in Containern, die du freigibst.** Alle anderen bleiben auch mit Schalter-Datei nur lesbar.
- **Nur in eingehängten Ordnern und unter `/home`.** Systemordner wie `/etc` oder `/usr` fasst PermLens nie an.
- **Nie root und nie Systemkonten.** Benutzer und Gruppen unter Nummer 1000 ändert PermLens nicht, und niemand kann über PermLens in `sudo` oder `root` aufgenommen werden.
- **Keine Passwörter.** PermLens zeigt den Befehl, das Passwort tippst du selbst im Container ein.
- **Der Wächter entscheidet.** Jeder Befehl wird auf dem Proxmox vom Wächter-Script geprüft, nicht nur in PermLens. Was er nicht kennt, lehnt er ab. Einzelheiten: [SICHERHEIT.md](SICHERHEIT.md).

## Einschalten und ausschalten

Auf dem **Proxmox-Host** (Weboberfläche → Knoten → „>_ Shell“). In die Datei kommen die Nummern der Container, in denen PermLens ändern darf, einzeln oder als Bereich:

```bash
mkdir -p /etc/permlens && echo '9001-9006' > /etc/permlens/schreiben-erlaubt
```

Ausschalten: Datei löschen oder leeren. Der Wächter liest sie bei jedem Befehl neu, PermLens zeigt den neuen Stand nach „Verbindung testen“.

```bash
rm -f /etc/permlens/schreiben-erlaubt
```

Dafür braucht der Proxmox das Wächter-Script **Version 7** (Einstellungen → „Neu einrichten“).

## So läuft jede Änderung ab

1. **Vorschau.** Noch passiert nichts. Du siehst:
   - den **genauen Befehl im Container** (zum Kopieren) und wie PermLens ihn ausführt (`pct exec <Nr> -- …`),
   - die **Einstufung** mit Begründung,
   - den Zustand **vorher und nachher**,
   - **was sich für die Benutzer ändert** („bob kann danach schreiben“), gerechnet wie bei Prüfen,
   - den **Befehl zum Rückgängigmachen**.
2. **Bestätigen.** Bei *harmlos* und *Vorsicht* ein Klick. Bei *Risiko* tippst du zusätzlich die Container-Nummer ein.
3. **Ausführen und nachprüfen.** PermLens prüft alles noch einmal frisch, führt den Befehl aus und liest danach nach, ob der Container so aussieht wie angekündigt. Weicht etwas ab, steht das da.
4. **Protokoll.** Jede Änderung steht auf der Seite **„Änderungen“** mit Zeit, Container, Befehl und Ergebnis. Dort gibt es auch den Knopf **„Rückgängig“**, wieder mit Vorschau.

### Die Einstufungen

| Einstufung | Bedeutung | Beispiele |
|---|---|---|
| **harmlos** | ändert nichts an bestehenden Rechten | Gruppe anlegen, Schreibtest |
| **Vorsicht** | erweitert oder entzieht Rechte, lässt sich leicht zurückdrehen | Benutzer in Gruppe aufnehmen, Rechte eines Ordners, ACL |
| **Risiko** | kann Zugriffe kaputt machen oder zu viel öffnen | ganze Ordnerbäume, Nummern ändern, Benutzer löschen, „andere“ dürfen schreiben |

## Wo du was findest

| Seite | Aktionen |
|---|---|
| **Prüfen** (bis 0.4.1 „Diagnose“) | unter „Sicher gehen“ der **„Echte Schreibtest“**; unter „So geht es“ der Knopf „Mit PermLens ausführen …“ an den Empfehlungen und „Selbst ändern: Besitzer, Rechte, ACL“, auch für den ganzen Ordner |
| **Container → Benutzer und Gruppen** | oben „Neuer Benutzer …“ und „Neue Gruppe …“; in jeder Zeile „Ändern …“: in Gruppe aufnehmen, Hauptgruppe, Nummer ändern, löschen; × an einer Gruppe entfernt die Mitgliedschaft |
| **Container → Ordner** | je Ordner „Prüfen“, „Rechte ändern …“ (öffnet Prüfen mit „Selbst ändern“) und „Dateien umnummerieren …“ |
| **Container → Überblick** | bei privilegierten Containern „Unprivilegiert machen …“ (Mapping-Assistent) |
| **Änderungen** | Protokoll und Rückgängig |
| **Einstellungen** | ob und für welche Container Ändern freigegeben ist |

## Alle Aktionen

Jeder Befehl läuft im Container, PermLens schickt ihn als `pct exec <Nr> -- <Befehl>` über den Wächter.

### Echter Schreibtest – harmlos

- **Was passiert:** Als der gewählte Benutzer wird eine leere Datei `.permlens-schreibtest-…` angelegt und sofort wieder gelöscht. So weißt du sicher, ob Schreiben klappt, auch bei NFS, wo die Rechnung nur ein Hinweis ist.
- **Befehl:** `setpriv --reuid=1001 --regid=1001 --groups=1000,1001 -- touch /mnt/share/.permlens-schreibtest-…` und danach `rm -f` derselben Datei.
- **Rückgängig:** nicht nötig, es bleibt nichts zurück. Lässt sich die Datei nicht löschen, sagt PermLens das mit Pfad.

### Gruppe anlegen – harmlos

- **Was passiert:** neue, leere Gruppe.
- **Befehl:** `groupadd -g 2001 projekt`
- **Rückgängig:** `groupdel projekt`

### Gruppe löschen – Vorsicht

- **Was passiert:** Die Gruppe verschwindet. Dateien, die ihr gehören, zeigen danach nur noch die Nummer.
- **Befehl:** `groupdel projekt`
- **Geht nur,** wenn die Gruppe keine Mitglieder hat und niemandes Hauptgruppe ist.
- **Rückgängig:** `groupadd -g 2001 projekt` (dieselbe Nummer, dann passt wieder alles).

### Besitzer eines Ordners ändern – Vorsicht

- **Was passiert:** Der Ordner (nur er, nicht der Inhalt) gehört danach einem anderen Benutzer bzw. einer anderen Gruppe.
- **Befehl:** `chown 1000:2000 /mnt/share`
- **Rückgängig:** `chown <alter Besitzer>:<alte Gruppe> /mnt/share`
- **Grenze:** Gehört der Ordner in einem unprivilegierten Container `nobody`, kann auch root im Container nichts ändern. Die Lösung liegt dann auf dem Host (siehe Prüfen und den Mapping-Assistenten).

### Rechte eines Ordners ändern – Vorsicht, Risiko wenn „andere“ schreiben dürfen

- **Was passiert:** neue Rechte für diesen einen Pfad.
- **Befehl:** `chmod 2775 /mnt/share`; aus einer Empfehlung auch `g+w` bzw. `o+x`, PermLens rechnet daraus die Zahl.
- **Rückgängig:** `chmod <alte Zahl> /mnt/share`. Hatte ein Ordner setgid und soll es wieder verlieren, steht eine führende 0 davor (`00755`), weil `chmod` es sonst behält.
- **Nie:** setuid (`4…`).

### ACL-Eintrag setzen oder entfernen – Vorsicht

- **Was passiert:** Genau ein Benutzer oder eine Gruppe bekommt eigene Rechte an diesem Pfad, zusätzlich zu Besitzer, Gruppe und „andere“, oder verliert sie wieder.
- **Befehl:** `setfacl -m u:1001:rwx /mnt/share`, `setfacl -x u:1001 /mnt/share`
- **Rückgängig:** der jeweils andere Befehl. Fällt der letzte eigene Eintrag weg, nimmt PermLens `setfacl -b`, damit wirklich der Zustand ohne ACL zurückkommt.
- **Braucht** im Container das Paket `acl`.

### Benutzer anlegen – Vorsicht

- **Was passiert:** neuer Benutzer mit Home-Ordner. Ohne Passwort kann er sich nicht anmelden.
- **Befehl:** `useradd -m -u 1003 -g 2000 dave`
- **Passwort, falls nötig, selbst im Container:** `passwd dave`
- **Rückgängig:** `userdel dave` (der Home-Ordner bleibt).

### Benutzer löschen – Risiko

- **Was passiert:** Der Benutzer verschwindet, seine Dateien bleiben und zeigen nur noch die Nummer. Der Home-Ordner bleibt.
- **Befehl:** `userdel dave`
- **Geht nur,** wenn der Benutzer in keiner weiteren Gruppe mehr ist (so lässt es sich genau zurückdrehen). Läuft ein Dienst als dieser Benutzer, lehnt `userdel` ab.
- **Rückgängig:** `useradd -m -u 1003 -g 2000 dave`

### In Gruppe aufnehmen oder entfernen – Vorsicht

- **Was passiert:** Der Benutzer darf danach alles, was die Gruppe darf, bzw. nicht mehr. Die Vorschau rechnet aus, was sich dadurch in jedem eingehängten Ordner ändert.
- **Befehl:** `usermod -aG media bob`, `gpasswd -d bob media`
- **Wichtig:** Laufende Dienste und angemeldete Sitzungen merken das erst nach einem Neustart bzw. einer neuen Anmeldung.
- **Rückgängig:** der jeweils andere Befehl.

### Hauptgruppe ändern – Vorsicht

- **Was passiert:** Neue Dateien des Benutzers gehören danach dieser Gruppe. `usermod` gibt dabei auch die Dateien im Home-Ordner, die der alten Hauptgruppe gehören, der neuen.
- **Befehl:** `usermod -g 2000 bob`
- **Rückgängig:** `usermod -g <alte GID> bob`

### Benutzer- oder Gruppennummer ändern – Risiko

- **Was passiert:** Der Benutzer bzw. die Gruppe bekommt eine neue Nummer. `usermod` stellt die Dateien im Home-Ordner gleich mit um. Alle anderen Dateien, zum Beispiel in eingehängten Ordnern, gehören danach der alten Nummer und damit niemandem. Die Vorschau zeigt, wie viele das in jedem Ordner sind.
- **Befehl:** `usermod -u 1007 bob`, `groupmod -g 2010 media`
- **Zweiter Schritt:** „Dateien umnummerieren“ (siehe unten).
- **Rückgängig:** `usermod -u <alte Nummer> bob` bzw. `groupmod -g <alte Nummer> media`
- **Grenze:** Läuft ein Prozess als dieser Benutzer, lehnt `usermod` ab.

### Dateien umnummerieren – Risiko

- **Was passiert:** Alle Dateien und Ordner unter einem eingehängten Ordner, die der alten Nummer gehören, bekommen die neue. Andere Dateien bleiben, wie sie sind.
- **Befehl:** `find /mnt/share -xdev -user 1001 -exec chown -h 1007 {} +` (bzw. `-group … -exec chgrp -h …`). `-xdev` bleibt auf einem Dateisystem, `-h` ändert Verknüpfungen selbst statt ihres Ziels.
- **Geht nur,** wenn der neuen Nummer vorher keine Datei gehört. Sonst ließe es sich nicht sauber zurückdrehen.
- **Rückgängig:** derselbe Befehl mit vertauschten Nummern.

### Ganzer Ordner (rekursiv): Besitzer, Rechte, ACL – Risiko

- **Was passiert:** Die Änderung gilt für alle Dateien und Ordner darunter. Vorher zählt PermLens sie (höchstens 200 000) und **sichert Besitzer, Rechte und ACLs aller Dateien** mit `getfacl -R`. Ohne Sicherung keine Änderung.
- **Befehle:** `chown -R -h 1000:2000 /mnt/share`, `chmod -R g+rwX,o-rwx /mnt/share` (`X` gibt `x` nur Ordnern; setuid und setgid gibt es rekursiv nicht), `setfacl -R -m g:2000:rwx /mnt/share`, als Standard für neue Dateien `setfacl -R -d -m g:2000:rwx /mnt/share`
- **Rückgängig:** PermLens spielt die Sicherung zurück (`setfacl --physical --restore`). Dateien, die seitdem neu dazugekommen sind, bleiben, wie sie sind.
- **Grenze:** Den Besitzer von Verknüpfungen selbst hält die Sicherung nicht fest.

## Was PermLens nicht kann

- **Rechte auf dem NAS bei NFS:** Ob ein NAS Schreiben erlaubt, entscheidet das NAS (Squash-Regeln, eigene Rechte-Listen). PermLens zeigt es mit dem Schreibtest, ändern musst du es im NAS.
- **Samba:** Freigaben, `smb.conf` und Samba-Passwörter (`smbpasswd`) macht der eigene Fileserver, nicht PermLens.
- **Benutzer auf dem Mac, auf dem NAS oder auf dem Proxmox-Host.**
- **Den Host selbst, ohne eigene Freigabe:** Mount-Punkte, `lxc.idmap`, `/etc/subuid` und `/etc/subgid` ändert PermLens erst ab 1.2.0 und nur mit der eigenen Schalter-Datei `/etc/permlens/host-aendern-erlaubt`, nur bei gestopptem Container: [MAPPING.md](MAPPING.md), [SICHERHEIT.md](SICHERHEIT.md). Container starten, stoppen oder anlegen tut PermLens nie.
- **Passwörter.**

## Beispiel von Anfang bis Ende

**Ziel:** immich und paperless-ngx sollen in denselben Ordner `/mnt/medien` schreiben, und der Mac soll über Samba alles lesen und kopieren dürfen. Der Ordner gehört `1000:1000` (luro), paperless schreibt als 1000, immich im Container als Benutzer `immich` (1001).

1. **Prüfen:** Container immich, Benutzer `immich`, Ordner `/mnt/medien` → *Schreiben: nein*, „Die Rechte erlauben es diesem Benutzer nicht“. Der **Schreibtest** bestätigt das.
2. **Gemeinsame Gruppe:** In beiden Containern unter Container → Benutzer und Gruppen mit „Neue Gruppe …“ die Gruppe `medien` mit derselben Nummer anlegen, z. B. 2000 (*harmlos*). Dieselbe Nummer heißt nur dann dieselbe Gruppe, wenn beide Container dasselbe Mapping haben (beide privilegiert oder beide Standard). Das zeigt der Reiter „Mapping“.
3. **Mitglieder:** `immich` bzw. `paperless` in `medien` aufnehmen (*Vorsicht*). Für `/mnt/medien` zeigt die Vorschau hier noch keine Änderung, weil der Ordner noch der Gruppe 1000 gehört. Das ändert Schritt 4.
4. **Ordner der Gruppe geben:** Bei Prüfen unter „Selbst ändern“: „Ganzer Ordner mit allem darunter“: Besitzer `1000:2000` (*Risiko*, mit Sicherung), danach Rechte `g+rwX`. Dann für den Ordner selbst (einzeln) die Rechte `2775`: Das setgid-Bit sorgt dafür, dass neue Dateien und Unterordner automatisch der Gruppe `medien` gehören.
5. **Für neue Dateien von Diensten,** die mit strengen Rechten schreiben: Standard-ACL `g:2000:rwx` für den ganzen Ordner (*Risiko*).
6. **Nachprüfen:** Prüfen für `immich` → *Schreiben: ja*, Schreibtest „klappt wirklich“. Die Dienste einmal neu starten, damit sie die neue Gruppe kennen.
7. **Mac:** Der Samba-Container schreibt mit `force user = luro`, also als 1000. Der Mac liest über die Gruppenrechte bzw. als Besitzer. Wenn Samba auch die Gruppe setzen soll: im Fileserver `force group = medien`.

Geht etwas schief: Seite „Änderungen“ → „Rückgängig“, von unten nach oben.
