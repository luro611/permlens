# Check and problems: why can (or can't) someone write?

*Deutsche Fassung: [DIAGNOSE.md](DIAGNOSE.md)*

PermLens answers the question **“Can user X in container Y read or write folder Z, and if not, why?”** It explains every step in plain language and tells you what you can do.

Checking itself **changes nothing**. All commands in the recommendations are for copying. If you have allowed changing for a container on the Proxmox host, PermLens can also carry out many recommendations itself, always with a preview first: see **[AENDERN.en.md](AENDERN.en.md)**. For a tour of all pages see the **[manual](MANUAL.md)**.

## The key point: the number counts, not the name

For every file, Linux stores not the owner's name but a **number** (UID for the user, GID for the group). The name is only a translation, and it can differ everywhere:

| Where | “luro” has, for example |
|---|---|
| Mac (first user) | UID 501 |
| Linux PC, container | UID 1000 |
| Proxmox host | maybe UID 1001, and 1000 has a completely different name there |
| Unprivileged container, seen from outside | UID 101000 |

So the same name does not mean the same user. That is where most permission problems come from.

**Privileged or unprivileged?**

- **Privileged container:** the numbers are the same inside and outside. root in the container is root on the host. That is convenient but isolates the container less.
- **Unprivileged container:** Proxmox shifts all numbers by 100000. 1000 in the container becomes 101000 on the host. A folder owned by 1000 on the host therefore belongs to **nobody** (65534) inside the container.
- **Custom mapping** (`lxc.idmap`): certain numbers are passed through 1:1, the rest is shifted.

## Where to find what

| Page | What for |
|---|---|
| **Overview** | The three most important problems, below that all containers and VMs |
| **Problems** | Everything PermLens found on its own during the scan, with a recommendation (see “Findings” below) |
| **Check** | The question “Who can write here?” |
| **Folder** | Every mounted folder with its owner and how it looks from each container. Further tabs: names and numbers compared, host storage with `/etc/subuid` and `/etc/subgid`. |
| **Container** (click in the overview) | Tabs At a glance, Users and groups, Folder (with shares for Samba or NFS servers) and Host settings |

## The “Check” page

1. **Choose a container:** only running containers can be checked, because only they have a user list.
2. **Choose a user:** regular users first, system users (e.g. `www-data`) below.
3. **Choose a folder:** the mounted folders are offered as buttons. You can also type your own path, PermLens then reads it fresh from the container.

You can also start a check from the container page: Folder tab, “Check” button next to the folder.

You get, from top to bottom:

- **Read yes/no** and **Write yes/no**, with the cause in one sentence below.
- **“How to fix it”:** recommendations with a command and a rating (see below). Whatever PermLens can carry out itself has a “Run with PermLens …” button. Below that, “Change it yourself: owner, permissions, ACL” in case no recommendation fits.
- **“Make sure”** (collapsed): the cross-check and the real write test (see below).
- **“How PermLens worked it out”** (collapsed): every folder on the way. To get into a folder, every folder before it needs `x`. Reading the target folder needs `r` and `x`, writing needs `w` and `x`.

### How PermLens calculates

Like Linux itself, in this order:

1. **root** may do anything. In an unprivileged container this only applies to files whose owner is mapped in the container. If something belongs to nobody, root is just “others” there.
2. If the user is the **owner**, the owner's permissions apply.
3. If there is an **ACL for the user**, it applies (limited by the mask).
4. If the user is in the folder's **group** or in an ACL group, their permissions apply. If a group matches but does not allow it, the answer is no. The permissions for “others” no longer count then.
5. Otherwise the permissions for **others** apply.

In addition, a folder mounted read-only (`ro=1`) always forbids writing.

### Possible causes

| Cause | Means |
|---|---|
| **nobody** | The owner on the host is not mapped in the unprivileged container. Only the permissions for “others” apply. |
| **path blocked** | A folder on the way does not let the user in (`x` is missing). |
| **permissions** | Owner, group or ACL do not allow it for this user. |
| **read only** | The folder is mounted read-only. |
| **missing** | The path does not exist in the container. |
| **no response** | The folder does not respond, usually because the NAS is switched off. |

### Make sure: cross-check and real write test

With NFS the NAS decides for itself, and some NAS devices keep their own permission lists. A folder may then show `rwxrwxrwx` and still refuse writes. For such cases there is **“Cross-check: ask the system itself”** under “Make sure”. PermLens asks inside the container **as this user** (`setpriv … test -r/-w/-x`) whether it works, without writing anything.

- **“Matches the calculation”**: everything is consistent.
- **“Differs from the calculation”**: another system also decides, usually the NAS.

**Limit with NFS:** some NAS devices answer the query differently from what they decide on an actual write. In a test with a UGREEN NAS the cross-check reported “read no, write yes”, yet the real write still failed. With NFS the cross-check is therefore a sign that the NAS decides differently, but no guarantee. Only a real write attempt is certain.

The cross-check needs guard script version 3 or later. Every cross-check is recorded in the PermLens log.

**Real write test:** if changing is allowed for the container, PermLens creates a small test file as this user and deletes it again right away. The result then reads “Writing really works” or “really does not work”. That is the reliable answer, even with NFS. Details: [AENDERN.en.md](AENDERN.en.md).

## The “Problems” page: findings

After every scan PermLens checks known sources of trouble on its own. The three most important ones appear at the top of the overview, all of them on the **Problems** page, and those of one container in its At a glance tab. Many have a “Run with PermLens …” button, a “Go to container” link or “Plan it in detail in the mapping assistant”. Every finding has a level:

- **Problem:** something does not work.
- **Note:** it works, but it is risky or fragile.
- **Info:** good to know, nothing to do.

| Finding | Level | Background |
|---|---|---|
| Mount source missing | Problem | A container is supposed to mount a host folder that does not exist. The container then does not start or only sees an empty folder. Often it is an old entry. |
| Container sees a folder as nobody | Problem | Unprivileged container, owner not mapped |
| Privileged container with host folders | Note | Convenient, but less isolated |
| Shared folder without setgid | Note | Several containers use the folder. New files get the wrong group, and the others often cannot change them. |
| Same name, different numbers | Note | e.g. `luro` is 1001 on the host, 1000 in the container |
| NFS export with `no_root_squash` | Note | root from the other device stays root |
| Same number, different names | Info | e.g. 1000 is called `paperless` on the host, `luro` in the Samba container |
| Samba share always writes as … | Info | `force user`: whoever logs in on the Mac, everything belongs to this user. |
| NFS / SMB | Info | With NFS the number counts, with SMB the mount options (`uid=`, `gid=`) |
| Unused entries in `/etc/subuid` / `/etc/subgid` | Info | Containers on Proxmox only use root's entries. |
| No response | Info | NAS switched off, not an error in the container |

## Rating of the recommendations

Every recommendation says **where** the command belongs (on the Proxmox host or in the container) and **how risky** it is:

| Rating | Means | Examples |
|---|---|---|
| **harmless** | Changes nothing about existing permissions | create a group |
| **caution** | Grants or removes permissions, easy to undo | `usermod -aG group user`, `chmod g+s folder`, remove an outdated mount point |
| **risk** | Can break access or open too much | change the mapping (`lxc.idmap`), `chown` on a shared folder, `chmod 777` |

Before a command rated **risk**: back up the container configuration, e.g. `cp /etc/pve/lxc/<id>.conf /root/<id>.conf.before`.

## Storage paths: who really writes in the end?

| Path | Example | What counts |
|---|---|---|
| Host folder mounted via `mpN` | `/mnt/data` → container | owner, permissions, ACL and the mapping |
| Host folder via `lxc.mount.entry` | as above, just configured differently | as above (host permissions from guard 3) |
| NFS share via the host | NAS → `/mnt/pve/…` → container | the number the container arrives with at the NAS. The NAS decides. |
| SMB share via the host | NAS → `/mnt/pve/…` → container | the mount options `uid=`, `gid=`, `file_mode=`. `chown` has no effect. |
| Container mounts NFS/SMB itself | its own `fstab` | like NFS or SMB |
| Container is a Samba server | Mac → share → container | `force user` / `force group`, otherwise the logged-in Samba user |
| Container is an NFS server | device → `/etc/exports` | `all_squash`/`anonuid`, otherwise the device's number |

**Example:** a Mac writes via a Samba share with `force user = luro`. In the Samba container that is number 1000. The container is privileged, so on the host it is 1000 too. The Mac's UID 501 does not matter.

## Numbers without a name

Many services run in Docker and write under a number for which there is no user in the container. paperless-ngx does this, for example, with `USERMAP_UID=1000`. The container page then shows in the Users and groups tab under **“Numbers without a name”** which number owns which folder and what it is called elsewhere. For permissions this is not an error, it is just harder to read.

## What PermLens cannot do

- **Read or change permissions on a NAS** (permission lists, squash rules of a Synology, UGREEN or TrueNAS). PermLens tells you that the fix lies there.
- **Manage Samba passwords and `smb.conf`.** A separate file server with its own interface does that.
- **Create users on the Mac, on Windows or on the Proxmox host.**
- **Look inside VMs.** VMs only appear in the list.
- **Change mapping and mount points on the host.** The mapping assistant shows the exact commands ([MAPPING.en.md](MAPPING.en.md)); you run them in the Proxmox shell. Letting PermLens do this itself is planned for after version 1.0. Users, groups and permissions **inside the container**, on the other hand, PermLens already changes if you allow it ([AENDERN.en.md](AENDERN.en.md)).
