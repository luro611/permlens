# Changing: permissions, users and groups with PermLens

*Deutsche Fassung: [AENDERN.md](AENDERN.md)*

From version 0.3.0 PermLens can carry out the recommendations of [Check and Problems](DIAGNOSE.en.md) itself: change owner, permissions and ACLs of folders, create and change users and groups in the container, change numbers and adjust whole folder trees. Every action is described here the way you would run it yourself in the container's terminal.

## The essentials first

- **Off until you switch it on on the Proxmox host.** Without the switch file PermLens only reads.
- **Only in containers you allow.** All others stay read-only even with the switch file.
- **Only in mounted folders and under `/home`.** PermLens never touches system folders such as `/etc` or `/usr`.
- **Never root and never system accounts.** PermLens does not change users and groups below number 1000, and nobody can be added to `sudo` or `root` through PermLens.
- **No passwords.** PermLens shows the command, you type the password yourself in the container.
- **The guard decides.** Every command is checked on the Proxmox host by the guard script, not only in PermLens. Whatever it does not know, it refuses. Details: [SICHERHEIT.md](SICHERHEIT.md) (German).

## Switching on and off

On the **Proxmox host** (web UI → node → “>_ Shell”). The file lists the containers in which PermLens may make changes, one by one or as a range:

```bash
mkdir -p /etc/permlens && echo '9001-9006' > /etc/permlens/schreiben-erlaubt
```

To switch off: delete or empty the file. The guard reads it again for every command; PermLens shows the new state after “Test connection”.

```bash
rm -f /etc/permlens/schreiben-erlaubt
```

This needs guard script **version 7** on the Proxmox host (Settings → “Set up again”).

## How every change works

1. **Preview.** Nothing happens yet. You see:
   - the **exact command in the container** (to copy) and how PermLens runs it (`pct exec <no> -- …`),
   - the **rating** with a reason,
   - the state **before and after**,
   - **what changes for the users** (“bob can write afterwards”), calculated as in Check,
   - the **command to undo it**.
2. **Confirm.** For *harmless* and *caution* one click. For *risk* you also type the container number.
3. **Run and verify.** PermLens checks everything again, runs the command and then reads the container again to see whether it looks as announced. If something differs, it says so.
4. **Log.** Every change appears on the **“Changes”** page with time, container, command and result. That is also where the **“Undo”** button is, again with a preview.

### The ratings

| Rating | Meaning | Examples |
|---|---|---|
| **harmless** | does not change existing permissions | create a group, write test |
| **caution** | grants or removes permissions, easy to undo | add user to group, permissions of a folder, ACL |
| **risk** | can break access or open too much | whole folder trees, changing numbers, deleting users, “others” may write |

## Where to find what

| Page | Actions |
|---|---|
| **Check** (until 0.4.1 “Diagnosis”) | under “Make sure” the **“Real write test”**; under “How to fix it” the “Run with PermLens …” button on the recommendations and “Change it yourself: owner, permissions, ACL”, also for the whole folder |
| **Container → Users and groups** | “New user …” and “New group …” at the top; “Change …” in every row: add to group, primary group, change number, delete; × on a group removes the membership |
| **Container → Folder** | per folder “Check”, “Change permissions …” (opens Check with “Change it yourself”) and “Renumber files …” |
| **Container → At a glance** | for privileged containers “Make unprivileged …” (mapping assistant) |
| **Changes** | log and undo |
| **Settings** | whether and for which containers changing is allowed |

## All actions

Every command runs in the container; PermLens sends it as `pct exec <no> -- <command>` through the guard.

### Real write test – harmless

- **What happens:** As the chosen user, an empty file `.permlens-schreibtest-…` is created and deleted right away. So you know for sure whether writing works, also with NFS where the calculation is only a hint.
- **Command:** `setpriv --reuid=1001 --regid=1001 --groups=1000,1001 -- touch /mnt/share/.permlens-schreibtest-…` followed by `rm -f` of the same file.
- **Undo:** not needed, nothing is left. If the file cannot be deleted, PermLens says so with its path.

### Create group – harmless

- **What happens:** new, empty group.
- **Command:** `groupadd -g 2001 projekt`
- **Undo:** `groupdel projekt`

### Delete group – caution

- **What happens:** The group disappears. Files owned by it then only show the number.
- **Command:** `groupdel projekt`
- **Only possible** if the group has no members and is nobody's primary group.
- **Undo:** `groupadd -g 2001 projekt` (same number, then everything fits again).

### Change owner of a folder – caution

- **What happens:** The folder (only the folder, not its contents) then belongs to another user or group.
- **Command:** `chown 1000:2000 /mnt/share`
- **Undo:** `chown <old owner>:<old group> /mnt/share`
- **Limit:** If the folder belongs to `nobody` in an unprivileged container, not even root in the container can change it. The fix is then on the host (see Check and the mapping assistant).

### Change permissions of a folder – caution, risk if “others” may write

- **What happens:** new permissions for this one path.
- **Command:** `chmod 2775 /mnt/share`; from a recommendation also `g+w` or `o+x`, PermLens calculates the number.
- **Undo:** `chmod <old number> /mnt/share`. If a folder had setgid and should lose it again, there is a leading 0 (`00755`), because `chmod` would otherwise keep it.
- **Never:** setuid (`4…`).

### Set or remove an ACL entry – caution

- **What happens:** Exactly one user or group gets its own permissions on this path, in addition to owner, group and “others”, or loses them.
- **Command:** `setfacl -m u:1001:rwx /mnt/share`, `setfacl -x u:1001 /mnt/share`
- **Undo:** the other command. If the last own entry goes away, PermLens uses `setfacl -b` so the state without ACL really comes back.
- **Needs** the `acl` package in the container.

### Create user – caution

- **What happens:** new user with a home folder. Without a password the user cannot log in.
- **Command:** `useradd -m -u 1003 -g 2000 dave`
- **Password, if needed, yourself in the container:** `passwd dave`
- **Undo:** `userdel dave` (the home folder stays).

### Delete user – risk

- **What happens:** The user disappears; their files stay and only show the number. The home folder stays.
- **Command:** `userdel dave`
- **Only possible** if the user is in no further group (so it can be undone exactly). If a service runs as this user, `userdel` refuses.
- **Undo:** `useradd -m -u 1003 -g 2000 dave`

### Add to or remove from group – caution

- **What happens:** The user may then do everything the group may do, or no longer. The preview calculates what changes in each mounted folder.
- **Command:** `usermod -aG media bob`, `gpasswd -d bob media`
- **Important:** Running services and logged-in sessions only notice after a restart or a new login.
- **Undo:** the other command.

### Change primary group – caution

- **What happens:** New files of the user then belong to this group. `usermod` also gives files in the home folder that belong to the old primary group to the new one.
- **Command:** `usermod -g 2000 bob`
- **Undo:** `usermod -g <old GID> bob`

### Change user or group number – risk

- **What happens:** The user or group gets a new number. `usermod` updates the files in the home folder at the same time. All other files, for example in mounted folders, then belong to the old number and so to nobody. The preview shows how many that are in each folder.
- **Command:** `usermod -u 1007 bob`, `groupmod -g 2010 media`
- **Second step:** “Renumber files” (see below).
- **Undo:** `usermod -u <old number> bob` or `groupmod -g <old number> media`
- **Limit:** If a process runs as this user, `usermod` refuses.

### Renumber files – risk

- **What happens:** All files and folders under a mounted folder that belong to the old number get the new one. Other files stay as they are.
- **Command:** `find /mnt/share -xdev -user 1001 -exec chown -h 1007 {} +` (or `-group … -exec chgrp -h …`). `-xdev` stays on one file system, `-h` changes symbolic links themselves instead of their targets.
- **Only possible** if no file belongs to the new number beforehand. Otherwise it could not be undone cleanly.
- **Undo:** the same command with the numbers swapped.

### Whole folder (recursive): owner, permissions, ACL – risk

- **What happens:** The change applies to all files and folders below. PermLens first counts them (at most 200,000) and **backs up owner, permissions and ACLs of all files** with `getfacl -R`. No backup, no change.
- **Commands:** `chown -R -h 1000:2000 /mnt/share`, `chmod -R g+rwX,o-rwx /mnt/share` (`X` gives `x` to folders only; no setuid or setgid recursively), `setfacl -R -m g:2000:rwx /mnt/share`, as default for new files `setfacl -R -d -m g:2000:rwx /mnt/share`
- **Undo:** PermLens restores the backup (`setfacl --physical --restore`). Files added since then stay as they are.
- **Limit:** The backup does not record the owner of symbolic links themselves.

## What PermLens cannot do

- **Permissions on the NAS with NFS:** Whether a NAS allows writing is decided by the NAS (squash rules, its own permission lists). PermLens shows it with the write test; you have to change it on the NAS.
- **Samba:** shares, `smb.conf` and Samba passwords (`smbpasswd`) are handled by the separate file server, not PermLens.
- **Users on the Mac, on the NAS or on the Proxmox host.**
- **The host itself, without its own permission:** PermLens changes mount points, `lxc.idmap`, `/etc/subuid` and `/etc/subgid` only from 1.2.0 on, only with the separate switch file `/etc/permlens/host-aendern-erlaubt` and only while the container is stopped: [MAPPING.en.md](MAPPING.en.md), [SICHERHEIT.en.md](SICHERHEIT.en.md). PermLens never starts, stops or creates containers.
- **Passwords.**

## Example from start to finish

**Goal:** immich and paperless-ngx should write to the same folder `/mnt/medien`, and the Mac should be able to read and copy everything via Samba. The folder belongs to `1000:1000` (luro), paperless writes as 1000, immich writes in its container as user `immich` (1001).

1. **Check:** container immich, user `immich`, folder `/mnt/medien` → *Write: no*, “The permissions do not allow this user”. The **write test** confirms it.
2. **Shared group:** In both containers under Container → Users and groups with “New group …” create the group `medien` with the same number, e.g. 2000 (*harmless*). The same number only means the same group if both containers have the same mapping (both privileged or both default). The “Mapping” tab shows this.
3. **Members:** add `immich` and `paperless` to `medien` (*caution*). For `/mnt/medien` the preview does not show a change yet, because the folder still belongs to group 1000. Step 4 changes that.
4. **Give the folder to the group:** In Check under “Change it yourself”: “Whole folder with everything below”: owner `1000:2000` (*risk*, with backup), then permissions `g+rwX`. Then for the folder itself (on its own) permissions `2775`: the setgid bit makes new files and subfolders belong to group `medien` automatically.
5. **For new files of services** that write with strict permissions: default ACL `g:2000:rwx` for the whole folder (*risk*).
6. **Check again:** Check for `immich` → *Write: yes*, write test “really works”. Restart the services once so they know the new group.
7. **Mac:** The Samba container writes with `force user = luro`, i.e. as 1000. The Mac reads through the group permissions or as the owner. If Samba should also set the group: `force group = medien` in the file server.

If something goes wrong: “Changes” page → “Undo”, from bottom to top.
