# Mapping: unprivileged containers with access to host folders

*Deutsche Fassung: [MAPPING.md](MAPPING.md)*

Many containers are **privileged** only because otherwise they could not write to shared folders. But privileged means weaker isolation: root in the container is root on the host. The **mapping assistant** (menu “Mapping”) shows how an **unprivileged** container can still write to these folders. It calculates everything and shows the commands for copying. **PermLens changes nothing on the host.** You run the commands yourself in the Proxmox host's shell.

## The essentials first: what “mapping” means

- An **unprivileged** container shifts all numbers by 100000: user 1000 in the container is 101000 on the host. A folder owned by 1000 on the host shows up as **nobody** (65534) in the container, and nobody in the container may write there, not even root.
- **`lxc.idmap`** lines in `/etc/pve/lxc/<no>.conf` pass single numbers through **1:1**: user 1000 in the container is then also 1000 on the host. All other numbers stay shifted, the container stays unprivileged.
- For Proxmox to allow this, root on the host has to allow these numbers in **`/etc/subuid`** and **`/etc/subgid`**, e.g. `root:1000:1`.
- If **Docker** runs in the container there is a third level: the app in the Docker container writes as the number from `PUID`/`PGID` (for paperless-ngx `USERMAP_UID`/`USERMAP_GID`). It has to match the passed-through number.

More on numbers and names: [DIAGNOSE.en.md](DIAGNOSE.en.md).

## The three tabs

| Tab | What for |
|---|---|
| **New container** | Blueprint for a container you are about to create |
| **Existing container** | An unprivileged container sees folders as nobody: which numbers to pass through additionally, and how |
| **Privileged → unprivileged** | Safely switch a privileged container; the old one stays as a fallback |

All three are rated **risk**: they change container settings and file owners. That is why there is always a way back and, at the end, a check with Check and the write test.

## New container: the blueprint

1. Enter up to four **host folders**, each with a target in the container and optionally “read only”. PermLens suggests folders already mounted in other containers, with owner and permissions. If PermLens does not know a folder yet, see its owner on the host with `ls -ldn <folder>`.
2. **Write as whom?** Leaving it empty means owner and group of the first folder. Further groups are possible (e.g. a shared group `medien` with 2000).
3. **Container number** (optional) and **app** (paperless-ngx, other Docker app, without Docker).

You get:
- for each folder, how it will look in the new container and whether reading and writing will work,
- which other containers see the same numbers (intended if they share the folders),
- the steps: create the container (unprivileged, for Docker `nesting` and `keyctl`, do not start it yet), add to `/etc/subuid`/`/etc/subgid` (only if needed), enter the `mpN` and `lxc.idmap` lines, start, values for the stack, optionally a user with the same number for checking,
- the blueprint as a text file, e.g. for LXC Forge.

## Existing container: the suggestion

For an **unprivileged** container whose folders show up as nobody. The finding “… sees … as nobody” under Problems also leads here, and so does the “Plan mapping …” button on the container page.

PermLens suggests passing through owner and group of these folders (never root) and shows each folder **today** and **afterwards**. The steps:

1. Back up the settings: `cp /etc/pve/lxc/<no>.conf /root/<no>.conf.vor-permlens`
2. Shut down the container: `pct shutdown <no>`
3. Add to `/etc/subuid`/`/etc/subgid` (only if needed).
4. Replace **only the `lxc.idmap` lines**. Snapshot sections (`[name]`) stay as they are.
5. **Fix up files:** what the container created as user 1000 so far is stored on the host as 101000 and would then be nobody. The command gives these files in the container's file system and in the folders to number 1000. Mount points are explicitly skipped (`-prune`) so the host folders themselves are not changed.
6. Start the container and check with PermLens.

**Way back:** restore the saved settings and give the files in the container back to the old numbers. Files in the host folders stay with the passed-through number, because there it cannot be told what was already like that before.

## Privileged → unprivileged: the switch

The safe way, also recommended by Proxmox: **back up and restore as a new, unprivileged container.** The old container stays unchanged as the fallback.

1. Backup: `vzdump <no> --storage <storage> --mode stop --compress zstd`
2. Shut down the old container, autostart off.
3. Restore under a **new** number: `pct restore <new> "$VOL" --unprivileged 1 --storage <storage> --ignore-unpack-errors 1`. Proxmox shifts all owners in the container by 100000.
4. `/etc/subuid`/`/etc/subgid` if needed.
5. Enter the mapping for the mounted folders.
6. Give files in the container back to the passed-through numbers (they were shifted during the restore).
7. If Docker runs in the container: `pct set <new> --features nesting=1,keyctl=1`.
8. Start the new container and check. For Samba: save a file from the Mac.
9. **Only after a few days** delete the old container.

Important:
- **Never run both at the same time.** The new one has the same network card and address as the old one.
- Run all commands one after another in **the same shell** (step 3 keeps the backup in `$VOL`).
- The new number stays. Proxmox cannot simply renumber containers.

**Way back:** shut down the new one (autostart off), start the old one again (autostart on). Remove the new one afterwards with `pct destroy <new>`.

## Limits

- **Folders owned by root:** root in the unprivileged container is 100000 on the host and may no longer write there. Either the service writes as a normal user, or the folder gets 100000 on the host (only if no other container needs it).
- **NFS and SMB from a NAS:** whether the NAS allows writing is decided by the NAS. Mapping only helps if the numbers on the NAS fit. The write test is certain.
- The blueprint does not take **ACLs** into account. Check after the switch does.
- **PermLens does not change `/etc/subuid`, `/etc/subgid` or `/etc/pve/lxc/<no>.conf` itself.** That deliberately stays with you (decision 2026-10-21).

## Example: paperless-ngx unprivileged with a shared folder

**Starting point:** the documents should live in `/mnt/appdata/paperless` on the host. The folder belongs to `1000:1000`. The Mac accesses it through the Samba container (`force user = luro`, i.e. 1000).

1. **Mapping → New container:** folder `/mnt/appdata/paperless`, target `/data`, app paperless-ngx, number e.g. 160. PermLens shows: in the container `1000:1000`, read ✓, write ✓.
2. On the Proxmox host: create container 160 unprivileged (Debian 13, `nesting` and `keyctl`), **do not start it**.
3. Run the commands from steps 2 and 3 of the blueprint: `root:1000:1` in `/etc/subuid` and `/etc/subgid` (if not there yet), then enter `mp0` and the `lxc.idmap` lines.
4. Start the container, set up Docker, register it in Dockhand.
5. In the paperless stack: `USERMAP_UID=1000`, `USERMAP_GID=1000`, and the folder `/data` as the volume for the documents.
6. Optionally in the container: `groupadd -g 1000 app; useradd -m -u 1000 -g 1000 app`, so PermLens can check.
7. PermLens: “Scan again”, Check: container 160, user `app`, folder `/data` → *Write: yes*. If changing is allowed for 160, also the real write test.
8. Let paperless consume a document. On the host the new file belongs to `1000:1000`, the Mac sees it via Samba.
