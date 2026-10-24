# Security: what PermLens does on your Proxmox host

*Deutsche Fassung: [SICHERHEIT.md](SICHERHEIT.md)*

PermLens needs access to your Proxmox host. This document describes **exactly** what the setup command changes on the host, what PermLens may and may not do afterwards, and where the limits are. Read it before you run the command.

> **Principle:** security does not depend on PermLens “behaving”. Even if someone takes over the PermLens LXC completely (password, Docker, SSH key), they can only do on the host what the guard script allows. The guard script lives on the host, belongs to root and cannot be changed from PermLens.

Some messages and file names are in German, as they appear on your system: the guard's log entries (`erlaubt` = allowed, `ABGELEHNT` = refused, `SCHREIBEN` = write) and the switch file `/etc/permlens/schreiben-erlaubt` (“writing allowed”).

## 1. What the setup command does on the host

The command PermLens shows looks like this (shortened):

```
f=$(mktemp) && if curl -fsSL http://<PermLens>/setup/<one-time-code> -o "$f" && echo "<checksum>  $f" | sha256sum -c --status; then bash "$f"; else echo "PermLens: … nichts ausgeführt." >&2; fi; rm -f "$f"
```

It downloads a short Bash script from PermLens into a temporary file, compares its SHA-256 checksum with the checksum in the command and runs it as root **only if they match**. The file is deleted afterwards. You can look at the script beforehand with `curl -fsSL http://<PermLens>/setup/<one-time-code>`.

The script does exactly these things and nothing else:

| Step | What happens | Which file |
|---|---|---|
| Check | Aborts if it is not running as root or `pct` is missing (not a Proxmox host). | – |
| 1/3 | Downloads the guard script, checks its SHA-256 checksum (it is part of the verified script) and stores it with permissions 755. An older version in the same place is replaced. | `/usr/local/sbin/permlens-guard` (new) |
| 2/3 | Appends **one** line. No line is ever deleted or changed. If the key is already there, nothing happens. | `/root/.ssh/authorized_keys` (one more line) |
| 3/3 | Reads the address, SSH port, node name and the **public** host key of the Proxmox host and sends them back to PermLens. | read only |

**The script explicitly does not:** install packages, restart services, change `sshd_config`, change the Proxmox firewall, create users, change anything about the cluster, Corosync, storage, containers or VMs, create API tokens, or read or transmit passwords.

The added line looks like this:

```
command="/usr/local/sbin/permlens-guard",restrict,from="192.168.1.50" ssh-ed25519 AAAA… permlens
```

- `command=…` – whatever command PermLens sends, SSH **always** starts only the guard script. There is no shell.
- `restrict` – no forwarding (ports, agent, X11), no terminal, no `~/.ssh/rc`.
- `from=…` – the key only works from the address of the PermLens LXC. A stolen key is useless from any other machine.

The one-time code is valid for one hour and for one setup only. Without a valid code PermLens does not hand out a script.

## 2. What PermLens may do on the host afterwards

The guard script compares every command with a fixed allow list. Anything that does not match exactly is refused (exit code 126). Commands are started without a shell, so special characters such as `;`, `|` or `$( )` have no effect. Every call, allowed or refused, is written to the system log: `journalctl -t permlens`.

**Allowed for reading (always), guard script version 7:**

| On the host | In the container (via `pct exec <id> --`) |
|---|---|
| `pct list`, `pct status <id>`, `pct config <id>` | `getent passwd`, `getent group` |
| `pvesh get /cluster/resources --type vm` (list of guests) | `findmnt` (mounted folders) |
| `cat` of exactly three files: `/etc/subuid`, `/etc/subgid`, `/etc/pve/storage.cfg` | `testparm -s` (Samba settings) |
| `getent passwd`, `getent group`, `findmnt` | `stat` for paths |
| `stat` and ACLs (owner and permissions only, **not** the content), and **only** for folders that are configured as a bind mount in a container (`mpN: /path,…` or `lxc.mount.entry: /path …` in `/etc/pve/lxc/<id>.conf`) | `cat /etc/exports` (the container's NFS exports, new in version 3), `getfacl -cpn <path>` (ACL of a path in the container, new in version 5) |
| | **Cross-check** (new in version 3): `setpriv --reuid=<n> --regid=<n> --clear-groups` or `--groups=<n>,…` `-- test -r`, `-w` or `-x <path>`. Asks the system, as this user, whether reading, writing or entering is allowed. `test` writes nothing, and `setpriv` only drops privileges, never adds any. The guard refuses programs other than `test` and checks other than `-r`, `-w`, `-x`. |

**What changed with version 3:** version 2 only knew sources from `mpN` lines on the host. Version 3 also recognises sources from `lxc.mount.entry` lines, and in the container additionally `cat /etc/exports` and the cross-check. All of it is read-only. Version 4 brought the first writing commands (section 3); reading did not change. Older versions keep working; PermLens then shows a note on the settings page. To update: Settings → “Set up again”, run the command in the Proxmox shell.

For all other paths on the host (e.g. `/root`, `/etc/pve/priv`) the guard gives no information. It reads the container configurations itself on every request, so PermLens cannot “slip” paths past it.

Without the switch file (section 3), PermLens therefore **cannot** change any file on the host or in a container, cannot start or stop containers, cannot read password files (`/etc/shadow` and `/etc/pve/priv/…` are not on the list) and cannot choose commands freely. The connection test checks this on every setup: it deliberately sends the forbidden command `id` and reports an error if the guard does not refuse it.

## 3. Writing (from guard script version 4)

**Allowed for writing, guard script version 7** (only inside the container, only for allowed containers):

| Command in the container (via `pct exec <id> --`) | Check by the guard |
|---|---|
| `groupadd -g <GID> <name>` (create group) | GID only 1000 to 59999, name only `a-z0-9_-` (starting with a letter or `_`, at most 32 characters), no further options |
| `groupdel <name>` (delete group) | as above; in addition the guard asks the container **itself** (`getent group <name>`) and refuses if the group has a number below 1000 (system group) |
| `chown <UID>:<GID> <path>` (owner, new in version 5) | only numbers from 0 to 60000 (never `nobody`), exactly one path, not recursive |
| `chmod <number> <path>` (permissions, new in version 5) | only octal (e.g. `2775`, `0755`), **never setuid** (`4…`), exactly one path, not recursive |
| `setfacl -m u:<n>:rwx <path>`, `setfacl -m g:<n>:r-x <path>`, `setfacl -x u:<n> <path>`, `setfacl -b <path>` (ACL, new in version 5) | exactly one entry for a user or group number, no default ACL, not recursive; `-b` removes all ACL entries of a path (PermLens uses it when the last own entry goes, so that the state without ACL really comes back) |
| `useradd -m -u <UID> -g <GID> <name>` (create user, new in version 6) | UID and GID only 1000 to 59999, name as for groups, no further options (so e.g. no `-o`, no custom shell) |
| `userdel <name>` (delete user, new in version 6) | without `-r`: the home folder is always kept; the guard checks in the container first (`getent passwd`) and refuses users below 1000 |
| `usermod -aG <group> <name>`, `gpasswd -d <name> <group>` (membership, new in version 6) | exactly one group; the guard checks user **and** group in the container and refuses everything below number 1000. So nobody can get into `sudo`, `root` or any other system group via PermLens |
| `usermod -g <GID> <name>` (primary group, new in version 6) | GID 1000 to 59999, user from 1000 (checked in the container) |
| `usermod -u <UID> <name>`, `groupmod -g <GID> <name>` (change number, new in version 7) | new number 1000 to 59999; user or group from 1000, checked in the container |
| `find <folder> -xdev -user <old> -exec chown -h <new> {} +` or `-group … -exec chgrp -h …` (renumber files, new in version 7) | exactly this form: stays on one file system (`-xdev`), changes symbolic links themselves rather than their target (`-h`), nothing other than `chown`/`chgrp` |
| `chown -R -h <UID>:<GID> <folder>`, `chmod -R <mode> <folder>`, `setfacl -R [-d] -m …`, `setfacl -R -x …` (recursive, new in version 7) | as the single commands; `chmod -R` also symbolic (e.g. `g+rwX,o-rwx`), but without `s` (recursively, setgid would also hit files), never setuid |
| `getfacl -R -p -n -P <folder>` (backup) and `find <folder> -xdev [-user|-group <n>] -printf .` (counting) | only in allowed containers, because they walk through the folders; counting only returns dots, no file names |
| `permlens-restore <folder>` (restore a backup, new in version 7) | not a real program: the guard reads the backup from standard input, checks **every** path in it (must be below the folder; `..` hidden in octal notation does not count either) and refuses backups that would set setuid. Only then does it pass it to `setfacl --physical --restore=-` |
| Write test (new in version 5): `setpriv --reuid=<n> --regid=<n> … -- touch <folder>/.permlens-schreibtest-<12 characters>` and `rm -f` of the same file (as this user or as root) | only exactly this file name, nothing else is created or deleted |

**Where PermLens may change things (from version 5):** owner, permissions, ACL, renumbering, backup, restore and the write test only work in the container's **mounted folders** (targets from `mpN: …,mp=/target` and `lxc.mount.entry` in `/etc/pve/lxc/<id>.conf`, which the guard reads itself) and below, as well as under `/home`. System folders such as `/etc`, `/usr` or `/` are never allowed. Before each of these commands the guard checks inside the container with `realpath -e` that the path exists and contains **no symbolic link**. This way a link inside a folder (e.g. to `/etc/shadow`) cannot be exploited.

PermLens never sets passwords (no `passwd`, no `chpasswd`).

**Recursive changes (from version 7):** beforehand PermLens backs up owner, permissions and ACLs of **all** files below with `getfacl -R` and stores the backup in its database. If the backup fails, nothing is changed. “Undo” restores exactly this backup. At most 200,000 files at once. Limit: the backup does not record the owner of symbolic links themselves.

These rules apply to all writing commands:

- They only work if the file `/etc/permlens/schreiben-erlaubt` exists on the host **and** the container is listed in it. **You** create this file by hand (`mkdir -p /etc/permlens && echo '9001-9006' > /etc/permlens/schreiben-erlaubt`) and can delete or empty it at any time. PermLens is then read-only again immediately. PermLens itself cannot create this file. The guard reads it anew for every command.
- **The file lists which containers PermLens may change**: numbers and ranges, separated by line breaks, commas or spaces, e.g. `9001-9006` or `140,150-152`. All other containers stay read-only even with the switch file. An empty file allows **nothing**. This way you can practise on test containers first and later allow individual real containers on purpose.
- The file is deliberately **not** in `/etc/pve`, so it only applies to this one node, not to the whole cluster.
- Even then there are no free commands, only individually allowed ones whose values are checked strictly (e.g. user name only from `a-z0-9_-`, UID only as a number). PermLens never changes root or system accounts (numbers below 1000).
- Every writing command appears in the system log (`journalctl -t permlens`) with `SCHREIBEN:`, refused ones with `ABGELEHNT`.
- In PermLens itself: before every change a preview shows the exact command, a rating (harmless, caution, risk), the state before and after and the command to undo it. For “risk” you also have to type the container number. Every change is listed on the “Changes” page and can be undone there.
- Creating users, `chown`, `chmod` and ACLs run **inside the container** via `pct exec`. They only change the file system of that container or the mounted folders, not the host system.
- Changes to the host configuration (idmap in `/etc/pve/lxc/<id>.conf`, `/etc/subuid`, `/etc/subgid`) are a separate, more dangerous level. So far PermLens only shows the commands for them (mapping assistant); carrying them out itself is planned for after version 1.0.

## 4. Proxmox cluster: what you need to know

- **`/root/.ssh/authorized_keys` applies to the whole cluster.** On Proxmox the file is a link to `/etc/pve/priv/authorized_keys`, and `/etc/pve` is distributed to all nodes. The PermLens line is therefore present on **all** nodes.
- That is still safe: the guard script is only installed on the node where you run the command. It is missing on the other nodes, and SSH aborts a login with the PermLens key there (there is no fallback shell).
- The cluster nodes also use this file to talk to each other (migration, replication, console). PermLens only appends and leaves all other lines untouched. **If you remove the line by hand, delete only the line ending in `permlens`.** A wrongly deleted line can break migrations and the console between nodes.
- If the cluster has no quorum, `/etc/pve` is read-only. The script then aborts with an error and has changed nothing (the guard script is already in place by then, which does no harm).
- `pvesh get /cluster/resources` shows the guests of all nodes (read only). Container details (`pct config`, `pct exec`) are only available for containers on the connected node.
- Corosync, HA, storage settings, firewall and certificates are not touched.

## 4a. Several Proxmox hosts (from PermLens 0.5.0)

- PermLens can be connected to several Proxmox hosts (e.g. at home and at work). You run the setup command once on each. Each gets its own guard script and its own line in `authorized_keys`, with the same PermLens key.
- **Each Proxmox host decides for itself whether PermLens may change things**, with its own file `/etc/permlens/schreiben-erlaubt`. A host without this file stays read-only, even if another one allows writing.
- PermLens always shows which Proxmox host is selected (below the top bar) and names it in every preview. A preview only applies to the host it was created for: if you switch in between (e.g. in another tab), PermLens does not carry it out.
- “Remove from PermLens” (Settings → Proxmox) only deletes the entry in PermLens. You remove the access on the Proxmox host itself as described in section 9.
- If PermLens is taken over, an attacker can do on **every** connected host what its guard allows. So only connect hosts you trust PermLens with, and only allow writing where you need it.

## 4b. Two-factor sign-in (from PermLens 0.5.2)

Optional, under **Settings → Two-factor sign-in**. Then the password alone is no longer enough: after the password PermLens asks for a six-digit code from an authenticator app (OTP Auth, Aegis, 2FAS, Google Authenticator …). The method is TOTP according to RFC 6238, as with Nextcloud.

- **Setup:** scan the QR code, then enter a code from the app. Only then is it switched on. This way you do not lock yourself out if scanning goes wrong.
- **The secret key** is stored only in the PermLens LXC in `/opt/permlens/data/totp.json` (permissions 600), never on the Proxmox host. Whoever takes over the LXC also has this key. Two-factor sign-in therefore protects against a leaked password, not against a compromised LXC.
- **A code is valid only once** and for about 30 seconds (a clock difference of half a minute in either direction is accepted). Failed attempts count as with the password: after 5 failures, 5 minutes lockout.
- **Between password and code** you have 5 minutes. The cookie for this does not count as being signed in.
- **Validity (from 0.5.4):** the sign-in ends when you close the browser. After that the password is always required. You enter the code from the app **once a day per browser**: a separate cookie remembers until midnight (time zone `TZ` of the container) that the code was entered. At midnight any open sign-in ends as well; after that you need the password and a new code. “Sign out” deletes both cookies. The daily cookie alone signs nobody in; the password is always required.
- Note: some browsers restore the last session including cookies on restart (e.g. “Continue where you left off”). You then stay signed in even after closing the browser. If you do not want that, use “Sign out”.
- **Recovery codes:** when switching it on, PermLens shows ten recovery codes once. Each replaces the code from the app once. Only their checksums are stored.
- **Switching it on or off signs out all other browsers.** Switching it off and creating new recovery codes require the current code from the app.
- **Phone lost, no recovery codes left:** run `rm /opt/permlens/data/totp.json` in the PermLens LXC. After that the password is enough again. Anyone who can do that has full access to the LXC anyway.
- Every step is recorded in the log (`login` with `zweiter_faktor`, `zwei-faktor`).

## 4c. “New version available” note (from PermLens 0.5.7)

- Shortly after start and then every six hours, PermLens queries `https://api.github.com/repos/luro611/permlens/releases/latest`. That is the public list of releases, without signing in.
- **The only thing sent along** is its own version number in the user agent (`PermLens/0.5.7 …`). No data from Proxmox, no identifier, no password. As with any request, GitHub sees the address of your internet connection.
- If there is a newer version, a link to the release appears at the bottom of every page. **Nothing is installed automatically**; you do that in Dockhand (Pull and Redeploy).
- **Switching it off:** Settings → Updates, untick the box. Or completely off with `UPDATE_CHECK=0` under `environment` in the stack file. Then PermLens never contacts GitHub, not even shortly after start.
- Switching it on or off is recorded in the log (`update-hinweis`).

## 5. How the PermLens image is built

The software itself should be traceable too (from version 0.2.1):

| What | How |
|---|---|
| **Python packages** | Every version is pinned and has a SHA-256 checksum (`requirements.txt`). When building, `pip --require-hashes` accepts only exactly these files. A replaced package on PyPI would abort the build. |
| **Base image** | `python:3.12-slim` is pinned not only by name but by digest (`@sha256:…`). Updates are deliberate: enter the new digest, build, test. |
| **No root** | Inside the container PermLens runs as its own user `permlens` (UID 10001), without special privileges (`no_new_privs`, no capabilities). Only at start does a small script take over the data folder once if it still belongs to root (data from older versions), and then drops all privileges. PermLens cannot change its own program code. |
| **No Docker socket** | The PermLens container has no access to Docker. |
| **SBOM and provenance** | Every image carries a list of all included packages (SBOM) and a record of the commit it was built from. To view: `docker buildx imagetools inspect ghcr.io/luro611/permlens:<version> --format '{{ json .SBOM }}'` |
| **No automatic build in the cloud** | The image is built by hand (`tools/publish.sh`), only from a state that is on GitHub. There are no GitHub Actions and therefore no runners that could see credentials. |

Not pinned are the two Debian packages `openssh-client` and `tzdata`: they come with Debian's current security updates at build time.

**If you want to decide yourself when a new version arrives,** put a fixed version instead of `:latest` into the stack file, e.g. `ghcr.io/luro611/permlens:0.5.7`, and change it yourself on every update.

## 6. Limits you should know about

To be honest, there are places where PermLens has to trust you and your home network:

1. **HTTPS with its own certificate (from 0.2.2).** PermLens encrypts with a self-generated certificate. The browser warns once; you can check the fingerprint (see [BETRIEB.md](BETRIEB.md), German). The setup command pins the certificate's key (`--pinnedpubkey`): a device that pushes itself between Proxmox and PermLens does not even get a connection. In addition the command checks the script's SHA-256 checksum as before. If you switch HTTPS off (`HTTPS=0`) or open PermLens via `http://`, you lose the first protection. Then only the checksum remains, and it comes via your browser.
2. **Whoever has PermLens has the guard's permissions.** Whoever knows the PermLens password or takes over the LXC can do everything the allow list permits: without the switch file only reading, with it the changes from section 3 in the allowed containers. Therefore: a strong `APP_PASSWORD`, ideally switch on two-factor sign-in (section 4b), never expose PermLens to the internet, keep the LXC up to date.
3. **Reading reveals something about the system.** PermLens sees user lists, mounts, storage configuration and the permissions of the mounted folders (not their content). That is the purpose of the program, but good to know.
4. **`pct exec` runs programs from the container.** `getent`, `stat` and so on come from the container. A manipulated container could give PermLens false information. It does not gain any more privileges than it already has, though.
5. **An existing line stays as it is.** If you once added the PermLens key without restrictions, the script does not change that. The connection test detects it (“guard refuses foreign commands” fails). Then delete the old line and set up again.

## 7. Recommended: firewall for the PermLens LXC

From outside, PermLens only needs the web interface, and outwards only SSH to the Proxmox host (plus, if switched on, HTTPS to `api.github.com` for the update note, section 4c). The Proxmox firewall can enforce this. Even a compromised PermLens LXC then cannot reach other devices in your home network.

**Caution:** the Proxmox firewall only takes effect when it is switched on under *Datacenter → Firewall → Options*. It then applies to the host as well. Proxmox keeps allowing the web interface (8006) and SSH from the local network. Still, make sure beforehand that you can reach the Proxmox console if needed.

In the Proxmox interface, for the PermLens LXC:

1. *Network* → edit `net0` → tick **Firewall**.
2. *Firewall → Options*: **Firewall: Yes**, **Input policy: DROP**, output policy **ACCEPT** for now.
3. *Firewall → Rules*, incoming (**in**, action **ACCEPT**, protocol **tcp**):

   | Destination port | Source | What for |
   |---|---|---|
   | `443` (or `8443`) and `80` (or `8000`) | your home network, e.g. `192.168.1.0/24` | PermLens web interface |
   | Hawser port (see the environment in Dockhand, usually `2376`) | only the IP of the Dockhand LXC | management via Dockhand (Hawser in standard mode) |

4. Optionally stricter, output policy **DROP** with these exceptions (**out**, **ACCEPT**): `tcp 22` only to the IP of the Proxmox host (PermLens), `udp/tcp 53` to the DNS server, `tcp 443` and `tcp 80` (image and package updates, update note). This is safer, but every new destination then has to be allowed.

Check: the web interface still works, *Test connection* in PermLens still works, and from another computer on the network the LXC answers on no other port, e.g. with `nmap <IP-of-the-LXC>`.

**Hawser and Dockhand:** whoever can operate Dockhand can also control the PermLens container via Hawser and thus use its SSH key. So protect your Dockhand access at least as well as PermLens itself: a strong password, and two-factor sign-in if your Dockhand version offers it.

## 8. Check it yourself

```bash
grep permlens /root/.ssh/authorized_keys
```

```bash
journalctl -t permlens --since today
```

```bash
sha256sum /usr/local/sbin/permlens-guard
```

The first line must start with `command="/usr/local/sbin/permlens-guard",restrict,from="…"`. The log should only contain entries with `erlaubt:` (allowed), except for the single `ABGELEHNT: id` (refused) from the connection test. Entries with `SCHREIBEN:` (write) only appear if you have allowed writing; each of them must match a line on the “Changes” page in PermLens.

## 9. Removing it completely

On the node where you set up PermLens (with several Proxmox hosts, on each of them):

```bash
cp /root/.ssh/authorized_keys /root/authorized_keys.vor-permlens
```

```bash
grep -v ' permlens$' /root/authorized_keys.vor-permlens > /root/.ssh/authorized_keys
```

```bash
rm -f /usr/local/sbin/permlens-guard && rm -rf /etc/permlens
```

The first command makes a backup, the second writes the file back without the lines ending in ` permlens`. The link to `/etc/pve/priv/` is kept. Do **not** use `sed -i`: it replaces the link with a regular file, and in a cluster the keys then no longer match. In a cluster it is enough to run the first two commands on one node. After that PermLens has no access at all.
