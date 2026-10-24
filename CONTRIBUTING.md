# Mitmachen / Contributing

Danke fürs Interesse an PermLens!

- **Fehler und Ideen** gern als [Issue](https://github.com/luro611/permlens/issues), auf Deutsch oder Englisch. Bei Fehlern bitte Version, Version des Wächter-Scripts und Proxmox-Version angeben.
- **Sicherheitslücken** nie als öffentliches Issue, siehe [SECURITY.md](SECURITY.md).
- **Pull Requests** bitte erst nach kurzer Absprache in einem Issue. PermLens greift auf Proxmox-Hosts zu, deshalb kommt jede Änderung am Wächter-Script (`host/permlens-guard`) oder an der Einrichtung nur nach genauer Prüfung hinein und wird in `docs/SICHERHEIT.md` beschrieben.
- **Entwickeln:** Python 3.12, `pip install -r requirements.txt -r requirements-dev.txt`, Tests mit `pytest`. Texte der Oberfläche sind deutsch, die englische Übersetzung steht in `app/locales/en.json` (ein Test prüft, dass keine fehlt).
- PermLens entsteht mit Hilfe von KI. Beiträge stehen wie das ganze Projekt unter der GPL-3.0-or-later.

---

Thanks for your interest in PermLens!

- **Bugs and ideas** are welcome as an [issue](https://github.com/luro611/permlens/issues), in English or German. For bugs, please include the PermLens version, the guard script version and the Proxmox version.
- **Vulnerabilities** never as a public issue, see [SECURITY.md](SECURITY.md).
- **Pull requests** please only after a short discussion in an issue. PermLens accesses Proxmox hosts, so any change to the guard script (`host/permlens-guard`) or the setup is only merged after careful review and documented in `docs/SICHERHEIT.md`.
- **Development:** Python 3.12, `pip install -r requirements.txt -r requirements-dev.txt`, tests with `pytest`. The interface texts are German; the English translation lives in `app/locales/en.json` (a test checks that none is missing).
- PermLens is built with the help of AI. Contributions are licensed like the whole project under GPL-3.0-or-later.
