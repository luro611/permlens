# Änderungen

## PermLens 1.2.0 – Änderungen am Host

**Wichtig beim Update:** Die neuen Funktionen brauchen auf dem Proxmox das **Wächter-Script Version 9** und eine **eigene Freigabe**. Nach dem Update in PermLens *Einstellungen → Neu einrichten* und den Befehl einmal auf jedem Proxmox ausführen. Ohne Freigabe ändert sich nichts: PermLens ändert am Host erst, wenn du die Datei `/etc/permlens/host-aendern-erlaubt` anlegst (Container-Nummern, dazu Zeilen mit `/` für Ordner, die neu eingehängt werden dürfen), z. B. `mkdir -p /etc/permlens && printf '9001-9006\n/srv/daten\n' > /etc/permlens/host-aendern-erlaubt`. `schreiben-erlaubt` gibt dafür nichts frei.

- **Mount-Punkte:** Container → Host-Einstellungen: „Mount-Punkt hinzufügen …“ und „Entfernen …“ je Ordner vom Host, mit Vorschau, nur bei gestopptem Container. Eingehängt werden nur Ordner, die schon in einem Container hängen oder unter einem freigegebenen Ordner liegen.
- **Mapping ausführen:** Mapping-Assistent → Bestehender Container → „Ausführen …“ trägt fehlende Zeilen in `/etc/subuid`/`/etc/subgid` ein und tauscht die `lxc.idmap`-Zeilen aus. Dateien im Container nachziehen bleibt von Hand (Befehl in der Vorschau, Häkchen zum Bestätigen).
- **Sicherung und Rückgängig:** Vor jeder Änderung sichert der Wächter `/etc/pve/lxc/<Nr>.conf` selbst. Unter „Änderungen“ spielt „Rückgängig“ die Sicherung zurück, solange die Datei seitdem niemand geändert hat.
- PermLens startet, stoppt und legt keine Container an. Alle Befehle von Wächter 9: `SICHERHEIT.md`, Abschnitt 3a.

**In English:** With guard script version 9 and the separate switch file `/etc/permlens/host-aendern-erlaubt`, PermLens can add and remove mount points and replace the mapping of existing, stopped containers, with preview, backup and undo. Updating files after a new mapping stays manual. After updating: *Settings → Set up again* on every Proxmox host.

**Update:** Dockhand → Pull → Redeploy, danach Neu einrichten (Wächter 9) / then set up again (guard 9).

## PermLens 1.1.2 – gespeicherte Baupläne

- **Baupläne speichern:** Im Mapping-Assistenten (Neuer Container) einen Bauplan unter einem Namen speichern, später laden, umbenennen und löschen. Gespeichert wird je Proxmox in der Datenbank von PermLens, ohne Container-Nummer; beim Laden rechnet PermLens mit dem aktuellen Stand neu.
- **Bauplan aus einer Docker-App:** Im Reiter Docker öffnet „Bauplan für neuen Container …“ den Mapping-Assistenten mit den Ordnern des Hosts und den Nummern der App.

**In English:** Save blueprints in the mapping assistant under a name, load, rename and delete them (per Proxmox). The Docker tab opens the mapping assistant prefilled from a running app.

**Update:** Dockhand → Pull → Redeploy. Kein Neu einrichten nötig / no new setup needed.

## PermLens 1.1.1 – Docker-Reiter mit langen Pfaden

- **Behoben:** Im Reiter Docker schob ein anonymes Docker-Volume (Pfad mit 64 Zeichen langer Kennung, z. B. bei hawser) die Tabelle über den Rand der Karte hinaus. Die Kennung wird jetzt gekürzt angezeigt (`b5db0401…e55b`), der volle Pfad steht im Tooltip, lange Pfade brechen um.

**In English:** Fixed: in the Docker tab, an anonymous Docker volume (path with a 64-character ID, e.g. with hawser) pushed the table beyond the card. The ID is now shortened, the full path is in the tooltip, long paths wrap.

**Update:** Dockhand → Pull → Redeploy. Kein Neu einrichten nötig / no new setup needed.

## PermLens 1.1.0 – Docker-Einblick und Nachschauen

**Wichtig beim Update:** Die neuen Funktionen brauchen auf dem Proxmox das **Wächter-Script Version 8**. Nach dem Update in PermLens *Einstellungen → Neu einrichten* und den Befehl einmal auf jedem Proxmox ausführen. Ohne das läuft alles wie bisher, nur ohne Docker-Reiter und ohne Konsole für Container. Alles, was dazukommt, liest nur.

### Docker-Apps

- **Neuer Reiter „Docker“** auf der Container-Seite, wenn im LXC Docker läuft: je App, als welche Nummer sie wirklich schreibt, wer das im Container und auf dem Proxmox ist, und je eingehängtem Ordner Besitzer, Lesen und Schreiben.
- **Schreibt als** misst PermLens an den laufenden Programmen der App. Viele Images starten als root und wechseln dann zu `PUID`; gezählt wird, als wer die eigentlichen Programme laufen. Läuft die App nicht, gelten `PUID`/`USERMAP_UID` aus der Stack-Datei oder der Benutzer aus dem Image.
- **Neue Probleme:** „App kann nicht in … schreiben“, „App schreibt als root“ (unprivilegierte Container), „App läuft nicht als `PUID`“.
- **Prüfen** kennt Docker-Apps als Benutzer, mit der passenden Empfehlung (`PUID`/`PGID` bzw. `user:` passend zum Ordner).
- Der Wächter gibt aus `docker inspect` nur ausgewählte Felder heraus. **Andere Umgebungsvariablen** (oft Passwörter und Tokens) und Befehlszeilen verlassen den Proxmox nie.

### Nachschauen

- **Konsole** für den schnellen Blick auf Host, Container oder Docker-App (*Zahnrad → Nachschauen*, auf der Container-Seite „Nachschauen →“). Sie sieht aus wie ein Terminal, kennt aber nur feste, lesende Befehle wie `id`, `ls -ld`, `stat`, `getfacl`, `df -h`, `docker ps`. Keine Shell, keine Dateiinhalte. `ls -l` (Inhalt eines Ordners) nur in Containern, in denen Ändern freigegeben ist.
- Ins Protokoll kommt nur, wann welcher Befehl lief, nie die Ausgabe.

### Außerdem

- Neue Anleitung **Installation** (seit 1.0.1), Anleitungen um Docker und Konsole ergänzt, `SICHERHEIT.md` mit allen Befehlen von Wächter 8.
- README verlinkt die Projektseite [lurohome.de/permlens](https://lurohome.de/permlens/).

**In English:** Docker apps: a new Docker tab shows, for every app in an LXC, which number it really writes as, who that is on the host and whether it may write to its folders; new problems and Check for apps. Quick look-up: a console with fixed, read-only commands for the host, a container or a Docker app. **Requires guard script version 8**: after updating, Settings → Set up again and run the command once on each Proxmox host. The guard never hands out other environment variables or command lines.

**Update:** Dockhand → Pull → Redeploy, danach *Einstellungen → Neu einrichten* / then *Settings → Set up again*.

## PermLens 1.0.1 – Installationsanleitung

Nur Dokumentation, am Programm ändert sich nichts.

- **Neue Installationsanleitung** [docs/INSTALLATION.md](https://github.com/luro611/permlens/blob/main/docs/INSTALLATION.md), auch auf Englisch ([docs/INSTALLATION.en.md](https://github.com/luro611/permlens/blob/main/docs/INSTALLATION.en.md)): was du brauchst, sechs Schritte vom leeren Proxmox bis zur Übersicht, alle Einstellungen der Stack-Datei und Hilfe bei Problemen mit den Meldungen, die PermLens und der Einrichtungs-Befehl zeigen können.
- **README:** Link „Installation“ ganz oben, der Abschnitt „Schnellstart“ heißt jetzt „Installation“.
- **BETRIEB.md** enthält nur noch, was nach der Installation kommt: neue Version, Neu einrichten, Sichern, Entfernen.

**In English:** documentation only, no changes to the program. New step-by-step [installation guide](https://github.com/luro611/permlens/blob/main/docs/INSTALLATION.en.md) with prerequisites, all stack file settings and troubleshooting.

**Update:** Dockhand → Pull → Redeploy (nicht nötig, wenn 1.0.0 läuft / not required if 1.0.0 is running).

## PermLens 1.0.0 – Erste öffentliche Version

PermLens ist ein Rechte-Manager für LXC-Container, derzeit speziell für Proxmox VE. Er zeigt, welche Benutzer es in deinen Containern gibt, wer sie auf dem Proxmox-Host sind und wer auf welche eingehängten Ordner und NAS-Freigaben zugreifen darf. Er erklärt Rechte-Probleme in Klartext und setzt die Lösung auf Wunsch selbst um, immer mit Vorschau und Rückgängig.

### Was PermLens kann

- **Ist alles in Ordnung?** Nach jedem Einlesen prüft PermLens von selbst bekannte Fehlerquellen: Ordner, die ein Container als `nobody` sieht, fehlende Mount-Quellen, gemeinsame Ordner ohne setgid, gleiche Namen mit verschiedenen Nummern, NFS mit `no_root_squash` und mehr. Jeder Befund mit Erklärung und Befehl.
- **Kann X hier schreiben?** Container, Benutzer und Ordner wählen. PermLens rechnet wie Linux selbst (Besitzer, Gruppe, ACL, Mapping, jeder Ordner auf dem Weg) und kann gegenprüfen: das System im Container fragen oder ein echter Schreibtest.
- **Benutzer und Gruppen ändern:** anlegen, Mitgliedschaften, Nummern, Besitzer, Rechte und ACLs im Container, auch für ganze Ordnerbäume mit Sicherung. Jede Änderung mit Vorschau, Einstufung, Protokoll und Rückgängig. Nur in Containern, die du auf dem Proxmox freigibst, nie root, nie Systemkonten, nie Passwörter.
- **Container unprivilegiert machen:** Der Mapping-Assistent rechnet `lxc.idmap`, `/etc/subuid` und `/etc/subgid` aus, für neue Container, für bestehende, die Ordner als nobody sehen, und für den Umstieg von privilegiert. Alle Befehle zum Kopieren, mit Weg zurück.
- **Außerdem:** mehrere Proxmox in einer Oberfläche, Benutzer in Klartext erklärt, die Einstellungen jedes Containers aus der conf-Datei, Zwei-Faktor-Anmeldung, HTTPS mit eigenem Zertifikat, Hinweis auf neue Versionen, Deutsch und Englisch, hell und dunkel.

### Sicherheit

PermLens spricht mit dem Proxmox nur per SSH mit eigenem Schlüssel. Der Schlüssel ist auf dem Host fest an ein Wächter-Script mit Erlaubnisliste gebunden, es gibt keine Shell und kein API-Token. Geschrieben wird nur, wenn du es auf dem Host ausdrücklich für einzelne Container freigibst. Das Image läuft ohne root, mit festen, geprüften Paketversionen, SBOM und Herkunftsnachweis. Alles Weitere: [docs/SICHERHEIT.md](https://github.com/luro611/permlens/blob/main/docs/SICHERHEIT.md).

### In English

PermLens is a permission manager for LXC containers, currently built for Proxmox VE. It shows which users exist in your containers, who they are on the host and who may access which mounted folders and NAS shares. It finds common permission problems on its own, answers “can X write here?” step by step, changes users, groups and permissions inside allowed containers with preview and undo, and helps you make containers unprivileged. Access to Proxmox is SSH only, bound to a guard script with a fixed allow list. See the [README](https://github.com/luro611/permlens/blob/main/README.md) and the [user manual](https://github.com/luro611/permlens/blob/main/docs/MANUAL.md).

**Einrichten / Setup:** [README](https://github.com/luro611/permlens/blob/main/README.md#schnellstart) · **Update:** Dockhand → Pull → Redeploy.

## PermLens 0.5.7 – Hinweis auf neue Versionen

Wie bei MediaDB (AP 5.4).

- **Neue Version verfügbar:** PermLens sieht kurz nach dem Start und danach alle sechs Stunden bei GitHub nach, ob es ein neueres Release gibt. Dann steht unten auf jeder Seite ein Link dorthin. Eingespielt wird nichts von selbst, das bleibt Pull und Redeploy in Dockhand.
- Gelesen wird nur die öffentliche Release-Liste von `luro611/permlens`. Mitgeschickt wird nur die Versionsnummer, keine Daten vom Proxmox.
- **Einstellungen → Updates:** diese Version, neueste bei GitHub, wann zuletzt nachgesehen, „Jetzt nachsehen“ und ein Schalter zum Abschalten. Ganz aus mit `UPDATE_CHECK=0` in der Stack-Datei.
- Solange das Repository privat ist, findet PermLens kein Release und zeigt still nichts an.
- `SICHERHEIT.md` Abschnitt 4c, `BETRIEB.md` und Stack-Datei ergänzt.

## PermLens 0.5.6 – Host-Einstellungen des Containers

Wunsch von Lutz: die conf-Datei eines Containers sehen, ohne in die Shell des Proxmox zu gehen, vor allem für den Umstieg privilegiert → unprivilegiert.

- **Container → Host-Einstellungen:** neuer Reiter mit allen Zeilen aus `/etc/pve/lxc/<Nr>.conf` (wie `pct config <Nr>`). Die Zeilen, die Rechte und Mapping bestimmen, sind hervorgehoben und erklärt (`unprivileged`, `mpN`, `lxc.mount.entry`, `lxc.idmap`, andere `lxc.*`, `features`). Darunter alles noch einmal als Text zum Kopieren.
- Bei privilegierten Containern steht dort, warum man `unprivileged: 1` nicht einfach nachträgt, mit Link zum Mapping-Assistenten.
- Die Notiz aus der Oberfläche von Proxmox erscheint nur auf Klick. Von Snapshots nennt PermLens nur die Namen.
- **Nur anzeigen.** Ändern kommt nach 1.0 (AP 4.5). Kein neuer Wächter nötig, `pct config` war schon erlaubt.
- Nach dem Update einmal „Neu einlesen“, vorher zeigt der Reiter einen Hinweis.

## PermLens 0.5.5 – Ersatz-Codes auf eigener Seite

- **Zwei-Faktor-Anmeldung:** Die zehn Ersatz-Codes erscheinen nach „Einschalten“ und „Neue Ersatz-Codes“ jetzt auf einer eigenen Seite. Bisher standen sie in den Einstellungen und waren je nach Browser nicht im Blick, weil die Seite zu einer anderen Stelle sprang.
- Die Seite wird vom Browser nicht zwischengespeichert.

## PermLens 0.5.4 – Code einmal am Tag

Wunsch von Lutz: Nach dem Schließen des Browsers immer das Passwort, den Code aber nur einmal am Tag.

- **Anmeldung endet mit dem Browser.** Bisher galt sie 7 Tage. Jetzt ist nach dem Schließen des Browsers immer das Passwort fällig.
- Nach dem Update meldet PermLens einmal alle ab, damit die alten 7-Tage-Anmeldungen nicht weiter gelten.
- **Code aus der App einmal am Tag je Browser:** Er gilt bis 24:00 Uhr. Bis dahin reicht in diesem Browser das Passwort. Um Mitternacht endet auch eine offene Anmeldung, dann braucht es Passwort und neuen Code. „Abmelden“ beendet beides.
- Einstellungen → Zwei-Faktor-Anmeldung nennt die Gültigkeit und empfiehlt **OTP Auth**. Jede andere App für zeitbasierte Codes (TOTP) geht auch.
- `SICHERHEIT.md`, Abschnitt 4b, ergänzt.

## PermLens 0.5.3 – QR-Code lässt sich scannen

- **Zwei-Faktor-Anmeldung:** Der QR-Code beim Einrichten war abgeschnitten (rechts und unten fehlte ein Streifen mit einer Eckmarke), deshalb konnte ihn keine App lesen. Jetzt wird er verkleinert statt abgeschnitten, mit weißem Rand ringsum.

## PermLens 0.5.2 – Zwei-Faktor-Anmeldung

Wunsch von Lutz: Anmelden wie bei all-inkl oder Nextcloud, mit einem Code aus der Handy-App.

- **Einstellungen → Zwei-Faktor-Anmeldung:** QR-Code mit der Authenticator-App scannen (OTP Auth, Aegis, 2FAS, Google Authenticator …), einen Code eingeben, fertig. Danach fragt die Anmeldung nach dem Passwort noch nach dem sechsstelligen Code.
- **Zehn Ersatz-Codes** für den Fall, dass das Handy fehlt. Sie werden einmal angezeigt und lassen sich mit einem Code aus der App erneuern.
- Ein Code gilt nur einmal. Fehlversuche führen wie beim Passwort nach 5 Versuchen zu 5 Minuten Sperre. Ein- und Ausschalten meldet alle anderen Browser ab.
- **Notausgang:** `/opt/permlens/data/totp.json` im LXC löschen, dann reicht wieder das Passwort.
- Neue Abhängigkeit `segno` (erzeugt den QR-Code, reines Python, ohne weitere Abhängigkeiten).
- Anleitungen: `SICHERHEIT.md` (neuer Abschnitt 4b) und `BETRIEB.md`.

## PermLens 0.5.1 – Benutzer in Klartext erklärt

Wunsch von Lutz: Die Benutzer-Seite soll auch Menschen ohne Linux-Wissen erklären, worum es geht.

- **Container → Benutzer und Gruppen:** Jeder Benutzer hat eine eigene Karte statt einer Tabellenzeile. Darin steht in Klartext, **wofür es ihn gibt** (Verwalter, persönliches Konto, Dienst-Konto, vermutlich von paperless-ngx angelegt, Samba schreibt als dieser Benutzer …) und **wer er auf dem Proxmox ist** (gleiche Nummer, durchgereicht oder verschoben, und was das für Dateien in gemeinsamen Ordnern heißt).
- **Rechte je Ordner:** Für jeden eingehängten Ordner zeigt die Karte Lesen ✓/✗ und Schreiben ✓/✗ mit einem ganzen Satz, warum (z. B. „bob ist weder Besitzer des Ordners noch in seiner Gruppe. Dann gilt, was ‚alle anderen‘ dürfen: lesen, aber nicht schreiben.“). Wo etwas nicht geht, führt „So geht es …“ direkt zur Lösung auf der Prüfen-Seite.
- **„So liest du diese Seite“:** kurze Erklärung von Nummer, Hauptgruppe, weiteren Gruppen, Nummer auf dem Proxmox und r/w/x.
- **Gruppen** mit Erklärung (eigene Gruppe eines Benutzers oder gemeinsame Gruppe, welche Ordner ihr gehören). **Systembenutzer** eingeklappt, jeder mit einer Zeile, wofür er da ist.
- **„Neuer Benutzer …“ und „Neue Gruppe …“:** Namensfeld über die ganze Breite, mit kurzer Erklärung.

## PermLens 0.5.0 – Mehrere Proxmox

- **PermLens kann mit mehreren Proxmox verbunden sein**, z. B. zu Hause und auf der Arbeit. Unter der Kopfzeile steht, welcher gerade gewählt ist, ein Klick schaltet um. Die Wahl gilt pro Browser.
- **Weiteren Proxmox hinzufügen** unter Einstellungen → Proxmox: zeigt einen Einrichtungs-Befehl. Auf dem neuen Proxmox ausgeführt, kommt er zur Liste dazu, statt den bisherigen zu ersetzen. Dort auch umbenennen und aus PermLens entfernen.
- **Eigener eingelesener Stand je Proxmox.** Beim Umschalten ist der letzte Stand sofort da.
- **Sicherheit beim Ändern:** Jede Vorschau nennt den Proxmox und gilt nur für ihn. Wurde inzwischen umgeschaltet (z. B. in einem anderen Tab), führt PermLens sie nicht aus. Das Protokoll „Änderungen“ zeigt die Einträge des gewählten Proxmox, Rückgängig geht nur dort. Ob geändert werden darf, entscheidet weiter jeder Proxmox selbst mit seiner Schalter-Datei.
- Gespeicherte Host-Schlüssel gelten je Proxmox: Ein neuer oder entfernter Proxmox lässt die Schlüssel der anderen unberührt.
- **Update von 0.4.x:** Die bisherige Verbindung und alle eingelesenen Stände werden beim ersten Start übernommen. Nichts neu einrichten.
- Anleitungen: `SICHERHEIT.md` (neuer Abschnitt 4a) und `BETRIEB.md`.

## PermLens 0.4.3 – Container-Seite mit Aktionen in den Zeilen (Usability, Schritt 3)

- **Drei Reiter** statt vier: **Überblick** (Probleme dieses Containers und Mapping), **Benutzer und Gruppen**, **Ordner** (eingehängte Ordner und Freigaben zusammen). Alte Adressen (`?tab=mapping`, `?tab=mounts`, `?tab=freigaben`) führen weiter zum passenden Reiter.
- **Ändern hängt an der Zeile:** „Ändern …“ bei jedem Benutzer (in Gruppe aufnehmen, Hauptgruppe, Nummer ändern, löschen) und jeder Gruppe (Mitglied aufnehmen, Nummer ändern, löschen). Oben die Knöpfe „Neuer Benutzer …“ und „Neue Gruppe …“. Die langen Formulare unten auf der Seite sind weg.
- **Ordner:** je Ordner „Prüfen“, „Rechte ändern …“ (öffnet Prüfen mit „Selbst ändern“ aufgeklappt) und „Dateien umnummerieren …“.
- **„Unprivilegiert machen …“** im Überblick privilegierter Container, „Mapping planen …“ bei unprivilegierten. Beides führt in den Mapping-Assistenten mit dem Container vorausgewählt.
- Prüfen: „Selbst ändern“ gibt es jetzt auch, wenn der Benutzer schon lesen und schreiben darf.
- Die Container-Seite stürzt nicht mehr ab, wenn für einen eingehängten Ordner die Angaben vom Host fehlen.

## PermLens 0.4.2 – Prüfen entschlackt (Usability, Schritt 2)

- **Seite „Prüfen“** (bisher „Diagnose“) in klarer Reihenfolge: zuerst die Antwort (Lesen ja/nein, Schreiben ja/nein) mit einem Satz dazu.
- **„Sicher gehen“** direkt darunter: Knopf „Echter Schreibtest“ und die Gegenprobe („das System selbst fragen“).
- **Ein Block „So geht es“** statt zwei: die Empfehlungen mit Befehl, Einstufung und „Mit PermLens ausführen …“, darunter eingeklappt „Selbst ändern: Besitzer, Rechte, ACL“ (einzeln und für den ganzen Ordner).
- **Rechenweg eingeklappt** („So hat PermLens gerechnet“). Die Befunde stehen seit 0.4.1 auf der Seite „Probleme“, hier nur noch ein Link mit den Zählern.
- Anleitung „Ändern“ (deutsch und englisch) an die neuen Namen angepasst.

## PermLens 0.4.1 – Neue Ordnung im Menü (Usability, Schritt 1)

- **Menü mit fünf Punkten** statt acht: Übersicht · **Probleme** · **Prüfen** (bisher Diagnose) · **Ordner** · Mapping. Einstellungen, Änderungen und Abmelden stehen im Zahnrad-Menü.
- **Neue Seite „Probleme“:** alle Befunde mit Empfehlungen, bisher ganz unten auf der Diagnose-Seite.
- **Übersicht:** unter dem Befunde-Zähler stehen die drei wichtigsten Probleme.
- **„Ordner“** fasst zusammen, was vorher auf drei Seiten verteilt war: eingehängte Ordner (bisher „Speicher“), Host mit Speichern und Nummernbereichen (bisher „Host“) und Namen und Nummern (bisher „Benutzer“). Die alten Adressen `/speicher`, `/host` und `/benutzer` leiten weiter.
- Keine neuen Funktionen, nur neu geordnet.

## PermLens 0.4.0 – Mapping-Assistent (Phase 4 abgeschlossen)

Mit 0.4.0 ist Phase 4 fertig. PermLens hilft, Container **unprivilegiert** zu betreiben und sie trotzdem in gemeinsame Ordner schreiben zu lassen. Es rechnet aus und zeigt die Befehle, am Host ändert es selbst nichts. Von Lutz auf dem Test-Proxmox abgenommen (2026-10-21). Alles seit 0.3.0 im Überblick:

- **Anleitung „Mapping“:** neu `docs/MAPPING.md` (englisch `docs/MAPPING.en.md`) mit allen Schritten, Grenzen und dem Beispiel „paperless-ngx unprivilegiert mit gemeinsamem Ordner“. Verlinkt aus README, der Anleitung „Ändern“ und der Seite „Mapping“.
- **Seite „Mapping“ mit drei Reitern:** Bauplan für neue Container, Vorschlag für bestehende Container (mit Dateien nachziehen und Weg zurück), Umstieg privilegiert → unprivilegiert (Sicherung, Wiederherstellen als neuer Container, alter bleibt als Rückfall).
- **Rechenkern** für `lxc.idmap`, fehlende `/etc/subuid`/`/etc/subgid`-Zeilen und gemeinsam genutzte Nummern.
- Seit 0.3.1: Ändern ist auch dann sichtbar, wenn es ausgeschaltet ist, mit Anleitung zum Freischalten.

## PermLens 0.3.4 – Umstieg privilegiert → unprivilegiert

- **Mapping, Reiter „Privilegiert → unprivilegiert“:** Geführte Anleitung für einen privilegierten Container (z. B. Samba oder paperless). Der alte Container bleibt erhalten, bis der neue geprüft ist: Sicherung mit `vzdump`, alten Container ausschalten (kein Autostart), Sicherung als **neuer** unprivilegierter Container unter einer freien Nummer wiederherstellen, `/etc/subuid`/`/etc/subgid` falls nötig, Mapping für die eingehängten Ordner, Dateien im Container den durchgereichten Nummern zurückgeben (Proxmox verschiebt sie beim Wiederherstellen um 100000), bei Docker die nötigen Funktionen, Start und Prüfung, erst ganz am Ende den alten Container löschen. Dazu der Weg zurück.
- Vorher ausgerechnet: wie jeder eingehängte Ordner im neuen Container aussieht; Warnung bei Ordnern, die auf dem Host root gehören (dort darf root im neuen Container nicht mehr schreiben).
- PermLens ändert dabei nichts am Host. Auf pve10 mit den erzeugten Befehlen geprüft: 9001 → 9101 unprivilegiert, alice schreibt weiter in den gemeinsamen Ordner, Dateien gehören auf dem Host wie vorher 1000:1000; Rückweg zu 9001 ausprobiert. Vorher von Hand mit dem Samba-Container 9003: Samba läuft unprivilegiert weiter.

## PermLens 0.3.3 – Mapping-Vorschlag für bestehende Container

- **Mapping, Reiter „Bestehender Container“:** Für einen unprivilegierten Container, der Ordner des Hosts als `nobody` sieht, schlägt PermLens vor, welche Nummern zusätzlich durchgereicht werden (vorausgewählt: Besitzer und Gruppe dieser Ordner, nie root), und zeigt je Ordner, wie er heute und danach im Container aussieht. Auswahl änderbar, weitere Nummern möglich.
- **Befehle in der richtigen Reihenfolge, zum Kopieren:** Einstellungen sichern, Container herunterfahren, `/etc/subuid`/`/etc/subgid` ergänzen (nur falls nötig), nur die `lxc.idmap`-Zeilen austauschen (Snapshots bleiben unberührt), **Dateien nachziehen**, die der Container schon unter diesen Nummern angelegt hat (sonst wären sie danach `nobody`), Container starten. Dazu „Zurück zum alten Stand“.
- Beim Nachziehen im Container-Dateisystem überspringt PermLens die Einhängepunkte ausdrücklich, damit die Ordner des Hosts selbst nicht mit umgestellt werden (beim Test aufgefallen und behoben).
- Der Befund „… sieht … als nobody“ verweist jetzt auf diesen Vorschlag.
- PermLens ändert dabei nichts am Host. Auf pve10 an 9002 hin und zurück geprüft: danach Besitzer auf dem Host und Einstellungen des Containers exakt wie vorher.

## PermLens 0.3.2 – Mapping-Assistent: Bauplan für neue Container (Phase 4 beginnt)

- **Neue Seite „Mapping“:** Bauplan für einen neuen **unprivilegierten** Container, der in Ordner des Hosts schreiben soll, ohne dass sich dort Besitzer ändern (z. B. paperless-ngx). Eingaben: Host-Ordner (Vorschläge mit Besitzer aus den schon eingehängten Ordnern), Ziel im Container, als wer geschrieben wird, App. Ausgabe zum Kopieren: `mpN`- und `lxc.idmap`-Zeilen für `/etc/pve/lxc/<Nr>.conf`, nur die fehlenden Zeilen für `/etc/subuid`/`/etc/subgid`, `USERMAP_UID`/`USERMAP_GID` bzw. `PUID`/`PGID` für den Stack, eine Schritt-für-Schritt-Liste und der Bauplan als Textdatei (auch für LXC Forge).
- **Vorher ausgerechnet:** wie jeder Ordner im neuen Container aussieht (Besitzer, `nobody`?) und ob Lesen und Schreiben klappen wird; Hinweis, welche anderen Container dieselben Nummern durchreichen oder privilegiert sind.
- **Rechenkern:** lückenlose `lxc.idmap`-Bereiche für eine oder mehrere durchgereichte Nummern, zusammenhängende Nummern zusammengefasst; nie 0 oder 65534.
- PermLens ändert dabei **nichts am Host**. Auf pve10 geprüft: neuer Container nach Bauplan, Diagnose „Schreiben: ja“, Dateien gehören auf dem Host dem Besitzer des Ordners.

## PermLens 0.3.1 – Ändern freischalten, gut sichtbar

- Ist Ändern für einen Container ausgeschaltet, zeigen die Container-Seite (Reiter „Benutzer“, Abschnitt „Benutzer und Gruppen ändern“) und die Diagnose jetzt einen Kasten „Ändern ist ausgeschaltet“: was mit Freigabe möglich wäre und die Schritte zum Freischalten, mit dem Befehl für genau diesen Container. Bisher fehlten die Formulare dann einfach.
- Einstellungen: „Ändern ein- oder ausschalten“ ist immer da und aufgeklappt, solange Ändern aus ist; bei einem zu alten Wächter-Script steht zuerst der Hinweis auf „Neu einrichten“.

## PermLens 0.3.0 – Ändern (Phase 3 abgeschlossen)

Mit 0.3.0 ist Phase 3 fertig. PermLens kann die Empfehlungen der Diagnose jetzt selbst umsetzen, immer mit Vorschau, Einstufung, Protokoll und Rückgängig, und nur in Containern, die du auf dem Proxmox freigibst. Von Lutz auf dem Test-Proxmox abgenommen (2026-10-21). Alles seit 0.2.0 im Überblick:

- **Anleitung „Ändern“:** neu `docs/AENDERN.md` (englisch `docs/AENDERN.en.md`): jede Aktion mit Befehl im Container, Einstufung, Rückgängig und Grenzen, dazu ein Beispiel von Anfang bis Ende (immich, paperless-ngx und Mac im selben Ordner). Verlinkt aus README, Diagnose-Anleitung und der Seite „Änderungen“.
- **Wächter-Script Version 7** mit Schalter-Datei `/etc/permlens/schreiben-erlaubt` (Container-Liste). Ohne Datei bleibt alles nur lesend. Schreiben nur in eingehängten Ordnern und unter `/home`, nie root oder Systemkonten, nie Passwörter.
- **Ordner:** Besitzer, Rechte, ACL, einzeln oder für den ganzen Ordner (mit vorheriger Sicherung), echter Schreibtest.
- **Benutzer und Gruppen im Container:** anlegen, löschen, Mitgliedschaften, Hauptgruppe, UID/GID ändern und Dateien umnummerieren.
- **Seite „Änderungen“** mit Protokoll und Rückgängig.
- `chmod -R` setzt kein setgid/setuid mehr (rekursiv träfe es auch Dateien); setgid für einen Ordner geht einzeln.

## PermLens 0.2.9 – Nummern ändern und ganze Ordner

- **Wächter-Script Version 7:** UID bzw. GID ändern (`usermod -u`, `groupmod -g`), Dateien umnummerieren (`find … -user|-group ALT -exec chown|chgrp -h NEU {} +`), rekursive Änderungen (`chown -R -h`, `chmod -R` auch symbolisch wie `g+rwX,o-rwx`, `setfacl -R`, auch als Standard-ACL für neue Dateien), Sicherung mit `getfacl -R` und `permlens-restore` zum Zurückspielen. Beim Zurückspielen prüft der Wächter jeden Pfad der Sicherung und lehnt setuid ab.
- **Rekursiv nur mit Sicherung:** Vor jeder rekursiven Änderung zählt PermLens die Dateien (höchstens 200 000) und sichert Besitzer, Rechte und ACLs aller Dateien. Ohne Sicherung keine Änderung. „Rückgängig“ spielt die Sicherung zurück und prüft danach nach.
- **Gleicher Name, andere Nummer:** Auf der Container-Seite unter „Nummern ändern“: UID/GID eines Benutzers bzw. einer Gruppe ändern (die Vorschau zeigt, wie viele Dateien in jedem eingehängten Ordner der alten Nummer gehören) und danach die Dateien umnummerieren. Umnummerieren geht nur, wenn der neuen Nummer vorher keine Datei gehört, damit es sich genau zurückdrehen lässt.
- **Diagnose:** unter „Diesen Pfad mit PermLens ändern“ neu „Ganzer Ordner mit allem darunter“ für Besitzer, Rechte und ACL.
- Alle diese Änderungen sind als Risiko eingestuft (Container-Nummer eintippen).

## PermLens 0.2.8 – Benutzer und Gruppen im Container

- **Wächter-Script Version 6:** Benutzer anlegen (`useradd -m -u -g`) und löschen (`userdel`, der Home-Ordner bleibt), in eine Gruppe aufnehmen (`usermod -aG`) und herausnehmen (`gpasswd -d`), Hauptgruppe ändern (`usermod -g`). Nur Benutzer und Gruppen ab Nummer 1000; der Wächter prüft das vorher selbst im Container nach, damit niemand in `sudo` oder eine andere Systemgruppe kommt. Passwörter setzt PermLens nie.
- **Container-Seite:** neuer Bereich „Benutzer und Gruppen ändern“ (neuer Benutzer mit vorgeschlagener Nummer, in Gruppe aufnehmen, Hauptgruppe ändern, Benutzer löschen); in der Gruppentabelle lässt sich ein Mitglied mit × entfernen.
- **Vorschau mit Folgen für die Ordner:** Bei Mitgliedschaften und Hauptgruppe rechnet PermLens für jeden eingehängten Ordner aus, ob der Benutzer danach lesen oder schreiben kann.
- **Diagnose:** Die Empfehlung „Benutzer in die Gruppe des Ordners aufnehmen“ hat jetzt einen Knopf „Mit PermLens ausführen …“.
- **Benutzer löschen** ist als Risiko eingestuft (Container-Nummer eintippen) und geht nur, wenn der Benutzer in keiner weiteren Gruppe mehr ist. So lässt es sich genau rückgängig machen.

## PermLens 0.2.7 – Ordner-Rechte ändern, echter Schreibtest

- **Wächter-Script Version 5:** Besitzer (`chown UID:GID`), Rechte (`chmod`, nie setuid) und ACL-Einträge (`setfacl -m/-x` für eine Nummer) für genau einen Pfad, dazu der echte Schreibtest. Nur in eingehängten Ordnern des Containers und unter `/home`; vorher prüft der Wächter im Container, dass der Pfad keine symbolische Verknüpfung enthält. Lesend neu: `getfacl` im Container.
- **Diagnose:** Empfehlungen wie `chmod g+w` oder `chmod o+x` haben einen Knopf „Mit PermLens ausführen …“. Unter „Diesen Pfad mit PermLens ändern“ lassen sich Besitzer, Rechte und ACL eines Pfads ändern, immer mit Vorschau.
- **Vorschau zeigt die Folgen:** Mit dem Rechte-Rechner aus Phase 2 steht in der Vorschau, welcher Benutzer des Containers danach lesen oder schreiben kann und wer es verliert.
- **Echter Schreibtest:** legt als der gewählte Benutzer eine leere Datei `.permlens-schreibtest-…` an und löscht sie sofort wieder. Sicher auch bei NFS, wo die Rechnung nur ein Hinweis ist. Weicht das Ergebnis von der Rechnung ab, sagt PermLens das.
- **Rückgängig auch für Ordner:** Der alte Besitzer, die alten Rechte bzw. der alte ACL-Eintrag werden vorher gelesen und mit „Rückgängig“ genau wiederhergestellt (bei Ordnern mit setgid mit führender 0, damit `chmod` das Bit wirklich entfernt). Wird der letzte eigene ACL-Eintrag entfernt, nimmt PermLens `setfacl -b`, damit wirklich der Zustand ohne ACL zurückkommt (sonst bliebe eine Maske stehen).
- **Gehört ein Pfad in einem unprivilegierten Container `nobody`,** sagt die Vorschau gleich, dass root im Container dort nichts ändern kann und die Lösung auf dem Host liegt, statt einen Versuch zu starten, der scheitern muss.

## PermLens 0.2.6 – Erste Änderungen (Phase 3 beginnt)

- **Wächter-Script Version 4:** Schalter-Datei `/etc/permlens/schreiben-erlaubt` mit den Nummern der Container, in denen PermLens ändern darf (z. B. `9001-9006`). Fehlt sie oder ist sie leer, bleibt alles nur lesend. Erste Schreibbefehle im Container: Gruppe anlegen (`groupadd -g`) und Gruppe löschen (`groupdel`, nur ab GID 1000, das prüft der Wächter selbst nach). Jeder Schreibbefehl steht mit `SCHREIBEN:` im Systemprotokoll.
- **Änderungen mit Vorschau:** genauer Befehl (zum Kopieren), Einstufung harmlos / Vorsicht / Risiko mit Begründung, Zustand vorher und nachher, Befehl zum Rückgängigmachen. Bei „Risiko“ wird zusätzlich die Container-Nummer eingetippt. Beim Ausführen wird alles frisch geprüft, danach liest PermLens den Container nach und meldet Abweichungen.
- **Neue Seite „Änderungen“:** alle Änderungen mit Befehl, Ergebnis und einem Knopf „Rückgängig“ (wieder mit Vorschau).
- **Container-Seite:** neuer Abschnitt „Gruppen“ mit Gruppe anlegen und leere Gruppe löschen, sobald der Container freigegeben ist.
- **Einstellungen:** zeigen, für welche Container Ändern freigegeben ist, und die Befehle zum Ein- und Ausschalten.
- `docs/SICHERHEIT.md`: neuer Abschnitt zu den Schreibbefehlen von Version 4.

## PermLens 0.2.5 – Neu einlesen, wo man es erwartet

- **„Neu einlesen“ fällt auf:** Der Knopf auf der Startseite ist jetzt ausgefüllt in Terrakotta. Die Befunde darunter sind zurückhaltender, damit sie nicht lauter wirken als die Hauptaktion.
- **„Verbindung testen“ liest gleich neu ein,** wenn die Verbindung klappt. Bisher blieb danach der alte Stand stehen, solange es derselbe Proxmox war.
- **Einstellungen zeigen den Stand:** In der Karte „Verbunden“ steht, wann zuletzt eingelesen wurde (oder dass gerade eingelesen wird), mit Link zur Übersicht.
- **Auch ein Fehler beim Speichern wird gemeldet:** Kann ein Einlesen nicht gespeichert werden, zeigt die Startseite einen Hinweis statt still den älteren Stand. Details stehen im Protokoll des Containers.

## PermLens 0.2.4 – Abgebrochenes Einlesen wird gemeldet

- Bricht das Einlesen mit einem internen Fehler ab, speichert PermLens das jetzt als neuen Stand. Die Startseite zeigt „Interner Fehler beim Einlesen (…)“, die Einzelheiten stehen im Protokoll des Containers (in Dockhand unter Logs). Bisher blieb in diesem Fall ohne Hinweis der alte Stand stehen, mit Containern, die es auf dem Proxmox gar nicht mehr gab.

## PermLens 0.2.3 – Was der Host sieht

- Neue Seite **Host** (nur lesen): alle Speicher aus `/etc/pve/storage.cfg` mit Art, Ort, erlaubtem Inhalt (Backups, ISO, Container-Platten …) und den Containern, die sie nutzen. Ein Speicher, den kein Container nutzt, etwa ein NAS nur für Backups, wird erklärt statt als Fehler gezeigt.
- Dazu: von Hand eingehängte Netzfreigaben (nicht in Proxmox eingetragen), Host-Ordner außerhalb der Speicher, Benutzer und Gruppen des Hosts und wofür jeder Eintrag in `/etc/subuid` und `/etc/subgid` gebraucht wird.
- Felder in `storage.cfg`, die nach Passwort oder Schlüssel klingen, liest PermLens nicht ein. Der Wächter bleibt bei Version 3, er erlaubte das Lesen von `storage.cfg` schon immer.

## PermLens 0.2.2 – HTTPS mit eigenem Zertifikat

- **HTTPS eingebaut:** Beim ersten Start erzeugt PermLens ein eigenes Zertifikat (`/opt/permlens/data/tls/`, 10 Jahre gültig). HTTPS läuft im Container auf Port 8443. Mit `HTTPS_PORT` in der Stack-Datei leitet der unverschlüsselte Port alles auf HTTPS um.
- **Einrichtungs-Befehl mit festgelegtem Schlüssel:** Über HTTPS nutzt der Befehl `curl --proto '=https' --pinnedpubkey …`. Der Proxmox lädt dann nur von genau diesem PermLens, zusätzlich zur Prüfsumme des Scripts.
- Anmelde-Cookie mit `Secure` über HTTPS. Die Einstellungsseite zeigt den Fingerabdruck des Zertifikats zum Vergleichen im Browser.
- **Übergang:** Ältere Stack-Dateien laufen weiter. PermLens zeigt dann einen Hinweis, welche zwei Zeilen fehlen.
- `docs/BETRIEB.md`: HTTPS und die Warnung beim ersten Besuch. `docs/SICHERHEIT.md`: neuer Abschnitt „Firewall für den PermLens-LXC“ und der Hinweis, den Dockhand-Zugang genauso gut zu schützen.

## PermLens 0.2.1 – Gehärtetes Image

- **Kein root mehr:** PermLens läuft im Container als eigener Benutzer `permlens` (UID 10001), ohne Capabilities und mit `no_new_privs`. Ein Daten-Ordner aus älteren Versionen wird beim ersten Start automatisch übernommen.
- **Feste Versionen mit Prüfsummen:** Alle Python-Pakete stehen mit Version und SHA-256 in `requirements.txt` (`pip --require-hashes`). Neu erzeugen mit `sh tools/lock.sh`.
- **Basis-Image per Digest** statt nur per Tag.
- **SBOM und Herkunftsnachweis** hängen an jedem Image.
- `docs/SICHERHEIT.md`: neuer Abschnitt „Wie das Image von PermLens gebaut ist“. `docs/BETRIEB.md`: Hinweis zum neuen Benutzer und zur festen Version statt `:latest`.

## PermLens 0.2.0 – Diagnose (Phase 2 abgeschlossen)

Mit 0.2.0 ist Phase 2 fertig. PermLens beantwortet jetzt „Kann Benutzer X auf Ordner Y lesen oder schreiben, und wenn nicht, warum?“. Es ändert weiterhin nichts. Alles seit 0.1.0 im Überblick:

- **Diagnose-Seite** mit Rechenweg (Besitzer, Gruppe, ACL, Mapping, Ordner auf dem Weg, schreibgeschützte Mounts) und **Gegenprobe** als echter Benutzer im Container (ab Wächter-Script Version 3).
- **Befunde** mit Stufe (Problem, Hinweis, Info) und **Empfehlungen** mit Befehl zum Kopieren und Einstufung harmlos, Vorsicht oder Risiko.
- **Benutzer-Seite:** Name und Nummer über Host und alle Container. Dazu „Nummern ohne Namen“ auf der Container-Seite und die Spalte „Benutzer und Gruppen“ auf der Übersicht.
- **Speicher-Wege:** Samba-Freigaben (`force user`), NFS-Exporte, eigene NFS/SMB-Mounts der Container, `lxc.mount.entry`.
- **Anleitung** [docs/DIAGNOSE.md](docs/DIAGNOSE.md) (Deutsch) und [docs/DIAGNOSE.en.md](docs/DIAGNOSE.en.md) (Englisch).

Neu in 0.2.0 gegenüber 0.1.5:

- Bei NFS weist die Gegenprobe darauf hin, dass sie nur ein Hinweis ist. In der Abnahme meldete eine UGREEN „Schreiben ja“, das echte Schreiben scheiterte trotzdem. Ein echter Schreibtest kommt mit Phase 3.

## PermLens 0.1.5 – Wächter-Script Version 3 und Gegenprobe

- **Wächter-Script Version 3** (nur lesend): Nach dem Update in PermLens unter Einstellungen „Neu einrichten“ wählen und den Befehl im Proxmox-Terminal ausführen. Die Einstellungsseite weist darauf hin, solange noch Version 2 läuft.
- **Gegenprobe** auf der Diagnose-Seite: PermLens fragt im Container als der gewählte Benutzer nach, ob Lesen und Schreiben wirklich geht (`setpriv … test -r/-w/-x`), ohne etwas zu schreiben. Weicht das von der Rechnung ab, etwa bei einem NAS über NFS, sagt PermLens das deutlich. Jede Gegenprobe steht im Protokoll.
- Ordner mit `lxc.mount.entry`: Besitzer, Rechte und ACLs auf dem Host werden jetzt gelesen.
- NFS-Server in Containern: Freigaben aus `/etc/exports` erscheinen im Reiter „Freigaben“ mit Erklärung (all_squash, anonuid, root_squash). Befund bei `no_root_squash`.
- `docs/SICHERHEIT.md` beschreibt die neuen Befehle des Wächters.

## PermLens 0.1.4 – Samba-Freigaben und Speicher-Wege

- Übersicht: neue Spalte **Benutzer und Gruppen**. Je Container stehen die neben root angelegten Benutzer und Gruppen (ab Nummer 1000), sonst „nur root“.
- Container-Seite: Hat eine Nummer auf dem Host einen anderen Namen, steht dort jetzt „heißt dort …“ (z. B. luro 1000 → heißt dort paperless). Es ist dieselbe Nummer, kein zusätzlicher Benutzer.
- Neuer Reiter **Freigaben** bei Samba-Containern: jede Freigabe mit Ordner, wer sich anmelden darf, als wer geschrieben wird (`force user`), Masken und dem Ordner auf dem Host. Dazu der Befund „Freigabe [x] schreibt immer als …“.
- Mounts: NFS- und SMB-Freigaben, die ein Container selbst einhängt, erscheinen jetzt mit Quelle, Optionen und Besitzer (`uid=`, `gid=`).
- Ordner, die mit `lxc.mount.entry` statt `mpN` eingehängt sind, werden erkannt und von innen gezeigt. Die Rechte auf dem Host dafür kommen mit Wächter-Script Version 3.
- Der Scan liest je laufendem Container zusätzlich `findmnt` und `testparm -s` und dauert dadurch etwas länger. Der Wächter bleibt bei Version 2.

## PermLens 0.1.3 – Benutzer über alle Container

- Neue Seite **Benutzer**: Für jeden Namen steht, welche Nummer (UID) er auf dem Host und in jedem Container hat. Namen mit verschiedenen Nummern stehen oben. Dazu für jede Nummer auf dem Host alle ihre Namen und die eingehängten Ordner, die ihr gehören.
- Container-Seite: **Nummern ohne Namen**. Gehört ein eingehängter Ordner einer Nummer, für die es im Container keinen Benutzer gibt (typisch bei Docker-Diensten wie paperless), zeigt PermLens sie mit ihren Namen auf dem Host und in anderen Containern.
- Befund „gleicher Name, verschiedene Nummern“ vergleicht jetzt auch mit den Benutzern des Hosts (z. B. luro auf dem Host 1001, im Samba-LXC 1000).
- Systemnummern ab 60000 (z. B. ceph) zählen nicht mehr als normale Benutzer.

## PermLens 0.1.2 – Diagnose und Befunde (Vorschau auf Phase 2)

- Neue Seite **Diagnose**: „Kann wer hier schreiben?“ Container, Benutzer und Ordner wählen, PermLens rechnet aus, ob Lesen und Schreiben klappt, und zeigt jeden Schritt: Besitzer, Gruppe, ACL, Mapping (nobody), schreibgeschützte Mounts und alle Ordner auf dem Weg. Eigene Pfade werden frisch aus dem Container gelesen. Bei NFS und SMB gibt es passende Hinweise.
- **Befunde:** PermLens erkennt von selbst fehlende Mount-Quellen, Ordner, die ein unprivilegierter Container als nobody sieht, privilegierte Container mit Host-Ordnern, gemeinsame Ordner ohne setgid, gleiche Nummer mit verschiedenen Namen (und umgekehrt), ungenutzte Einträge in `/etc/subuid` und `/etc/subgid` und ausgeschaltete NAS. Stufen: Problem, Hinweis, Info. Zähler auf der Übersicht, Liste auf der Diagnose-Seite, passende Befunde auf Container- und Speicher-Seite.
- **Empfehlungen:** Zu jedem Problem steht, was man tun kann, mit Befehl zum Kopieren (z. B. fertige `lxc.idmap`-Zeilen, `usermod -aG`, `chmod g+s`) und Einstufung harmlos / Vorsicht / Risiko. PermLens selbst ändert weiterhin nichts.
- Container-Seite: „Prüfen“ bei jedem Benutzer und jedem Mount.
- Der Scan liest zusätzlich die Ordner auf dem Weg zu jedem Mount-Ziel. Der Wächter bleibt bei Version 2.

## PermLens 0.1.1 – Wächter-Version immer sichtbar

- Einstellungen: Die Karte „Verbunden“ zeigt jetzt immer die Version des Wächter-Scripts auf dem Proxmox, nicht nur nach „Verbindung testen“. PermLens merkt sie sich bei jedem Verbindungstest und jedem Einlesen. Läuft auf dem Proxmox eine ältere Version als die mitgelieferte, erscheint ein Hinweis, dass „Neu einrichten“ sie aktualisiert.

## PermLens 0.1.0 – Erste Version: Rechte ansehen (nur lesen)

- Grundgerüst: Web-App im MediaDB-Design (Farben, Schriften, Hell/Dunkel), Deutsch und Englisch, `/healthz`, Docker-Image und Stack-Datei für Dockhand.
- Anmeldung: Passwort ist Pflicht (`APP_PASSWORD`, mindestens 8 Zeichen), nur aus dem Heimnetz erreichbar, nach 5 Fehlversuchen 5 Minuten Sperre, Abmelden. Anmeldungen landen im Protokoll (`data/permlens.db`).
- Verbindung zum Proxmox: Einstellungsseite mit eigenem SSH-Schlüssel, fertigen Befehlen für den Host und Verbindungstest. Neues Wächter-Script `host/permlens-guard` lässt nur lesende Befehle aus einer Erlaubnisliste zu und protokolliert jeden Aufruf (`journalctl -t permlens`). ACLs liest es selbst, `getfacl` muss nicht installiert sein.
- Übersicht: alle LXCs und VMs mit einfacher Ampel (läuft, gestoppt, nicht lesbar), privilegiert/unprivilegiert, Mapping (Standard, eigenes, 1:1) und Anzahl Mounts. „Neu einlesen“ holt frische Daten, die letzten 30 Scans werden gespeichert. Ein Scan von 36 Gästen dauert etwa 12 Sekunden.
- Container-Seite mit drei Reitern: **Benutzer** (UID, GID, Gruppen, wer sie auf dem Host sind, Systembenutzer eingeklappt), **Mapping** (Bereiche Container → Host, durchgereichte Nummern, privilegiert = 1:1) und **Mounts** (Quelle, Art: Ordner, NFS, SMB, Volume, Besitzer und Rechte auf dem Host und im Container, ACLs, Warnung bei fehlender Quelle und bei „nobody“).
- Speicher-Ansicht: jeder Host-Ordner und jede Freigabe, die in Container eingehängt ist, mit allen Containern, die sie nutzen, und dem Besitzer, wie ihn jeder Container sieht. Dazu NFS/SMB-Freigaben des Hosts, die in keinem Container stecken.
- Einrichtung mit **einem Befehl** auf dem Proxmox: Wächter installieren, Schlüssel erlauben, Adresse, Port und Host-Schlüssel zurückmelden. Danach liest PermLens sofort ein und springt zur Übersicht. Nummer und Adresse des LXC sind egal.
- Scan läuft im Hintergrund, die Übersicht aktualisiert sich von selbst. Jeder Ordner wird einzeln mit 10 Sekunden Zeitlimit abgefragt: Eine ausgeschaltete NAS hält den Scan nicht mehr auf und erscheint als „Keine Antwort – NAS ausgeschaltet?“.
- Übersicht zeigt zuerst nur die laufenden Container und VMs, die gestoppten lassen sich aufklappen.
- Fußzeile: „Gebaut von luro mit Hilfe von KI“. „luro“ ist die Wortmarke (lu + kursives ro in Terrakotta) und verlinkt auf lurohome.de. Auf der Anmeldeseite steht das luro-Siegel, es passt sich hell und dunkel an.
- Das Passwort kommt als Variable `APP_PASSWORD` aus Dockhand, nicht mehr direkt aus der Stack-Datei.
- Sicherheit: Neue Anleitung [docs/SICHERHEIT.md](docs/SICHERHEIT.md) beschreibt genau, was die Einrichtung auf dem Host verändert, was PermLens darf und was im Cluster gilt.
- Sicherheit: Der Einrichtungs-Befehl führt das Script nur noch aus, wenn seine Prüfsumme stimmt (statt `curl … | bash`). Die Adresse von PermLens wird streng geprüft, bevor sie ins Script kommt.
- Sicherheit: Wächter Version 2. `stat` und `acl` auf dem Host antworten nur noch für Ordner, die in einem Container als Bind-Mount (`mpN`) eingetragen sind.
- Neu einrichten: Die Seite springt nicht mehr sofort zur Übersicht, sondern wartet, bis der neue Befehl auf dem Proxmox gelaufen ist. „Kopieren“ funktioniert jetzt auch ohne HTTPS (z. B. Safari über http://). Klappt es nicht, wird der Befehl markiert.
