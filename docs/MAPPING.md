# Mapping: Unprivilegierte Container mit Zugriff auf Ordner des Hosts

*English version: [MAPPING.en.md](MAPPING.en.md)*

Viele Container sind nur deshalb **privilegiert**, weil sie sonst nicht in gemeinsame Ordner schreiben dürfen. Privilegiert schottet aber schwächer ab: root im Container ist root auf dem Host. Der **Mapping-Assistent** (Menü „Mapping“) zeigt, wie ein **unprivilegierter** Container trotzdem in diese Ordner schreiben kann. Er rechnet alles aus und zeigt die Befehle zum Kopieren. **Am Host ändert PermLens dabei nichts.** Die Befehle führst du selbst in der Shell des Proxmox-Hosts aus.

## Das Wichtigste vorab: Was „Mapping“ heißt

- Ein **unprivilegierter** Container verschiebt alle Nummern um 100000: Benutzer 1000 im Container ist auf dem Host 101000. Ein Ordner, der auf dem Host 1000 gehört, erscheint im Container als **nobody** (65534), und niemand im Container darf dort schreiben, auch root nicht.
- Mit **`lxc.idmap`**-Zeilen in `/etc/pve/lxc/<Nr>.conf` reicht man einzelne Nummern **1:1** durch: Benutzer 1000 im Container ist dann auf dem Host auch 1000. Alle anderen Nummern bleiben verschoben, der Container bleibt unprivilegiert.
- Damit Proxmox das darf, muss root auf dem Host diese Nummer in **`/etc/subuid`** und **`/etc/subgid`** freigeben, z. B. `root:1000:1`.
- Läuft im Container **Docker**, gibt es eine dritte Ebene: Die App im Docker-Container schreibt als die Nummer aus `PUID`/`PGID` (bei paperless-ngx `USERMAP_UID`/`USERMAP_GID`). Die muss zur durchgereichten Nummer passen.

Mehr zu Nummern und Namen: [DIAGNOSE.md](DIAGNOSE.md), Abschnitt „Es zählt die Nummer, nicht der Name“.

## Die drei Reiter

| Reiter | Wofür |
|---|---|
| **Neuer Container** | Bauplan für einen Container, den du gleich neu anlegst |
| **Bestehender Container** | Ein unprivilegierter Container sieht Ordner als nobody: welche Nummern zusätzlich durchreichen, und wie |
| **Privilegiert → unprivilegiert** | Einen privilegierten Container sicher umstellen; der alte bleibt als Rückfall erhalten |

Alle drei sind als **Risiko** einzustufen: Sie ändern Einstellungen von Containern und Besitzer von Dateien. Deshalb gibt es überall einen Weg zurück und am Ende die Prüfung mit Prüfen und Schreibtest.

## Neuer Container: der Bauplan

1. **Ordner des Hosts** eintragen, bis zu vier, jeweils mit Ziel im Container und auf Wunsch „nur lesen“. PermLens schlägt Ordner vor, die schon in anderen Containern eingehängt sind, mit Besitzer und Rechten. Kennt PermLens einen Ordner noch nicht, siehst du den Besitzer auf dem Host mit `ls -ldn <Ordner>`.
2. **Als wer schreiben?** Leer lassen heißt: Besitzer und Gruppe des ersten Ordners. Weitere Gruppen sind möglich (z. B. eine gemeinsame Gruppe `medien` mit 2000).
3. **Container-Nummer** (optional) und **App** (paperless-ngx, andere Docker-App, ohne Docker).

Du bekommst:
- je Ordner, wie er im neuen Container aussieht und ob Lesen und Schreiben klappen werden,
- welche anderen Container dieselben Nummern sehen (gewollt, wenn sie sich die Ordner teilen),
- die Schritte: Container anlegen (unprivilegiert, für Docker `nesting` und `keyctl`, noch nicht starten), `/etc/subuid`/`/etc/subgid` ergänzen (nur falls nötig), `mpN`- und `lxc.idmap`-Zeilen eintragen, starten, Werte für den Stack, optional einen Benutzer mit derselben Nummer zum Prüfen,
- den Bauplan als Textdatei, z. B. für LXC Forge.

**Baupläne speichern:** Unter dem fertigen Bauplan einen Namen eingeben (z. B. „paperless mit /mnt/appdata“) und speichern. Gespeichert werden Ordner, Ziele, Nummern und App, nicht die Container-Nummer. Die Liste „Gespeicherte Baupläne“ oben im Reiter zeigt alle Baupläne dieses Proxmox; „Laden“ füllt das Formular wieder aus und rechnet mit dem aktuellen Stand neu, unter „Ändern …“ lassen sie sich umbenennen und löschen. Gleicher Name ersetzt einen gespeicherten Bauplan.

**Aus einer Docker-App:** Im Reiter *Docker* der Container-Seite führt „Bauplan für neuen Container …“ hierher, vorbelegt mit den Ordnern des Hosts, die die App nutzt (am selben Ziel wie im bisherigen LXC), und den Nummern, als die sie schreibt. Docker-Volumes und Ordner, die nur im LXC liegen, kommen nicht in den Bauplan; die Seite sagt dazu, welche.

## Bestehender Container: der Vorschlag

Für einen **unprivilegierten** Container, dessen Ordner als nobody erscheinen. Den Weg dorthin zeigt auch der Befund „… sieht … als nobody“ unter Probleme, und auf der Container-Seite der Knopf „Mapping planen …“.

PermLens schlägt vor, Besitzer und Gruppe dieser Ordner durchzureichen (nie root), und zeigt je Ordner **heute** und **danach**. Die Schritte:

1. Einstellungen sichern: `cp /etc/pve/lxc/<Nr>.conf /root/<Nr>.conf.vor-permlens`
2. Container herunterfahren: `pct shutdown <Nr>`
3. `/etc/subuid`/`/etc/subgid` ergänzen (nur falls nötig).
4. **Nur die `lxc.idmap`-Zeilen** austauschen. Snapshot-Abschnitte (`[name]`) bleiben, wie sie sind.
5. **Dateien nachziehen:** Was der Container bisher als Benutzer 1000 angelegt hat, liegt auf dem Host bei 101000 und wäre danach nobody. Der Befehl gibt diese Dateien im Container-Dateisystem und in den Ordnern der Nummer 1000. Die Einhängepunkte werden dabei ausdrücklich übersprungen (`-prune`), damit die Ordner des Hosts selbst nicht mit umgestellt werden.
6. Container starten und mit PermLens prüfen.

**Zurück:** gesicherte Einstellungen zurückspielen und die Dateien im Container wieder den alten Nummern geben. Dateien in den Ordnern des Hosts bleiben bei der durchgereichten Nummer, weil sich dort nicht unterscheiden lässt, was vorher schon so war.

**Selbst ausführen lassen (ab PermLens 1.2.0, Wächter-Script Version 9):** Unter den Schritten steht „Ausführen …“. PermLens erledigt dann Schritt 1, 3 und 4 in einem Durchgang über den Wächter: Der Wächter sichert die Einstellungen selbst, hängt fehlende `root:N:1`-Zeilen an und schreibt die neuen `lxc.idmap`-Zeilen. Den Container fährst du vorher selbst herunter (Schritt 2) und startest ihn danach (Schritt 6). **Schritt 5 (Dateien nachziehen) bleibt von Hand**: Die Vorschau zeigt die Befehle, und Ausführen geht erst nach dem Häkchen „Ich ziehe die Dateien selbst nach (oder es gibt keine)“. Zurück geht es unter „Änderungen“ → „Rückgängig“ (spielt die Sicherung zurück). Voraussetzung: Der Container steht in `/etc/permlens/host-aendern-erlaubt`, siehe [SICHERHEIT.md](SICHERHEIT.md#3a-ändern-am-host-ab-wächter-script-version-9-permlens-120). Mount-Punkte hinzufügen und entfernen geht genauso auf der Container-Seite im Reiter „Host-Einstellungen“.

## Privilegiert → unprivilegiert: der Umstieg

Der sichere Weg, den auch Proxmox empfiehlt: **sichern und als neuer, unprivilegierter Container wiederherstellen.** Der alte Container bleibt unverändert und ist der Rückfall.

1. Sicherung: `vzdump <Nr> --storage <Speicher> --mode stop --compress zstd`
2. Alten Container ausschalten, Autostart aus.
3. Wiederherstellen unter einer **neuen** Nummer: `pct restore <Neu> "$VOL" --unprivileged 1 --storage <Speicher> --ignore-unpack-errors 1`. Proxmox verschiebt dabei alle Besitzer im Container um 100000.
4. `/etc/subuid`/`/etc/subgid`, falls nötig.
5. Mapping für die eingehängten Ordner eintragen.
6. Dateien im Container den durchgereichten Nummern zurückgeben (sie wurden beim Wiederherstellen verschoben).
7. Läuft Docker im Container: `pct set <Neu> --features nesting=1,keyctl=1`.
8. Neuen Container starten, prüfen. Bei Samba: eine Datei vom Mac aus ablegen.
9. **Erst nach einigen Tagen** den alten Container löschen.

Wichtig:
- **Nie beide gleichzeitig laufen lassen.** Der neue hat dieselbe Netzwerkkarte und Adresse wie der alte.
- Alle Befehle in **derselben Shell** nacheinander ausführen (Schritt 3 merkt sich die Sicherung in `$VOL`).
- Die neue Nummer bleibt. Proxmox kann Container nicht einfach umnummerieren.

**Zurück:** neuen ausschalten (Autostart aus), alten wieder einschalten (Autostart an). Den neuen danach mit `pct destroy <Neu>` entfernen.

## Grenzen

- **Ordner, die root gehören:** root im unprivilegierten Container ist auf dem Host 100000 und darf dort nicht mehr schreiben. Entweder schreibt der Dienst als normaler Benutzer, oder der Ordner bekommt auf dem Host 100000 (nur, wenn ihn kein anderer Container braucht).
- **NFS und SMB vom NAS:** Ob das NAS Schreiben erlaubt, entscheidet das NAS. Mapping hilft nur, wenn die Nummern auf dem NAS dazu passen. Sicher ist der Schreibtest.
- **ACLs** rechnet der Bauplan nicht mit. Prüfen nach dem Umstellen tut es.
- **`/etc/subuid`, `/etc/subgid` und `/etc/pve/lxc/<Nr>.conf` ändert PermLens nur mit eigener Freigabe** (ab 1.2.0, Schalter-Datei `/etc/permlens/host-aendern-erlaubt`) und nur für bestehende, gestoppte Container. Neue Container, der Umstieg privilegiert → unprivilegiert und das Nachziehen von Dateien bleiben bei dir.

## Beispiel: paperless-ngx unprivilegiert mit gemeinsamem Ordner

**Ausgangslage:** Die Dokumente sollen in `/mnt/appdata/paperless` auf dem Host liegen. Der Ordner gehört `1000:1000`. Der Mac greift über den Samba-Container darauf zu (`force user = luro`, also 1000).

1. **Mapping → Neuer Container:** Ordner `/mnt/appdata/paperless`, Ziel `/data`, App paperless-ngx, Nummer z. B. 160. PermLens zeigt: im Container `1000:1000`, Lesen ✓, Schreiben ✓.
2. Auf dem Proxmox-Host: Container 160 unprivilegiert anlegen (Debian 13, `nesting` und `keyctl`), **nicht starten**.
3. Die Befehle aus Schritt 2 und 3 des Bauplans ausführen: `root:1000:1` in `/etc/subuid` und `/etc/subgid` (falls noch nicht da), dann `mp0` und die `lxc.idmap`-Zeilen eintragen.
4. Container starten, Docker einrichten, in Dockhand anmelden.
5. Im paperless-Stack: `USERMAP_UID=1000`, `USERMAP_GID=1000`, und den Ordner `/data` als Volume für die Dokumente.
6. Optional im Container: `groupadd -g 1000 app; useradd -m -u 1000 -g 1000 app`, damit PermLens prüfen kann.
7. PermLens: „Neu einlesen“, Prüfen: Container 160, Benutzer `app`, Ordner `/data` → *Schreiben: ja*. Ist Ändern für 160 freigegeben, zusätzlich der echte Schreibtest.
8. Ein Dokument einlesen lassen. Auf dem Host gehört die neue Datei `1000:1000`, der Mac sieht sie über Samba.
