# Installing PermLens

*Deutsche Fassung: [INSTALLATION.md](INSTALLATION.md)*

This guide takes you step by step from a plain Proxmox host to the first overview in PermLens. Expect about 15 minutes.

PermLens runs as a Docker container in its own LXC on your Proxmox host. It is most convenient to manage with **Dockhand**; without Dockhand, `docker compose` works just as well.

> **Important:** PermLens gets access to your Proxmox host. **Never** expose it to the internet; use it only on your home network. Please read [SICHERHEIT.en.md](SICHERHEIT.en.md) before step 5.

## What you need

- A **Proxmox VE** host with access to the web interface and the node shell (as root).
- A **free, fixed IP address** on your home network for the PermLens LXC, e.g. outside your router's DHCP range or with a fixed assignment in the router.
- A Debian 13 container template (in Proxmox: *local → CT Templates → Templates*).
- Optionally **Dockhand**, if you already manage your Docker stacks with it.

## 1. Create the LXC

In the Proxmox web interface, *Create CT* with these values:

| Setting | Value |
|---|---|
| Template | Debian 13 |
| Type | **unprivileged** (leave “Unprivileged container” ticked) |
| CPU / RAM / disk | 1 core, 512 MB (swap 512 MB), 8 GB. Measured: PermLens needs about 50 MB when idle, the whole LXC with Docker and Hawser about 200 MB. |
| Network | **fixed IP address**, e.g. `192.168.1.50/24` with your router as gateway. PermLens' SSH key will later only be valid from this address. |

After creating it, enable **`nesting`** and **`keyctl`** under *Options → Features* (required for Docker). Then start the container.

## 2. Docker in the LXC

In the LXC's shell (Proxmox web interface → container → *Console*):

```bash
apt-get update && apt-get install -y docker.io
```

**With Dockhand:** create a new environment for the LXC in Dockhand (Hawser agent) and run the command it shows inside the LXC, just like for your other LXCs. Dockhand then shows the environment as connected.

## 3. Start PermLens

First create the data folder, also in the LXC's shell:

```bash
mkdir -p /opt/permlens/data
```

**With Dockhand:** in the LXC's environment, create a new stack “permlens” and paste the contents of [`docker-compose.homelab.yml`](../docker-compose.homelab.yml). The password is not in the file: under the **stack's variables**, add a variable `APP_PASSWORD` with your password as its value (at least 8 characters). Then click *Deploy*.

**Without Dockhand:** in the LXC

```bash
cd /opt/permlens && curl -O https://raw.githubusercontent.com/luro611/permlens/main/docker-compose.homelab.yml
```

```bash
echo 'APP_PASSWORD=your-password' > /opt/permlens/.env && docker compose -f docker-compose.homelab.yml up -d
```

`docker ps` (container `permlens`, status *Up*) or Dockhand shows whether PermLens is running. `docker logs permlens` shows its start-up messages.

Tip: if PermLens runs alone in its own LXC, put `"80:8000"`, `"443:8443"` and `HTTPS_PORT=443` in the stack file. It is then reachable at `https://<IP-of-the-LXC>` without a port number.

## 4. Open it in the browser

Open `https://<IP-of-the-LXC>:8443` and sign in with your password. `http://<IP-of-the-LXC>:8000` redirects there automatically. The interface starts in German; the **EN** button in the header switches to English (also on the sign-in page).

**The warning on the first visit:** on its first start PermLens creates **its own certificate** (in `/opt/permlens/data/tls/`, valid for 10 years). Because no certificate authority signed it, the browser warns you (“Not secure” or “Your connection is not private”). This is how you check that it really is your PermLens:

1. Open the warning in the browser and view the certificate. Note the **SHA-256 fingerprint**.
2. Look it up in the LXC:
   ```bash
   docker exec permlens openssl x509 -in /app/data/tls/cert.pem -noout -fingerprint -sha256
   ```
3. If both match, save the exception in the browser. Later the fingerprint is also shown under *Settings*.

The setup command in the next step pins this certificate's key (`curl --pinnedpubkey`). The Proxmox host then only downloads from exactly this PermLens.

**Recommended:** right after the first sign-in, add a code from an authenticator app under *Settings → Two-factor sign-in* ([SICHERHEIT.en.md, section 4b](SICHERHEIT.en.md#4b-two-factor-sign-in-from-permlens-052)).

## 5. Connect to Proxmox

> **Please read first:** [Security: what PermLens does on your Proxmox host](SICHERHEIT.en.md). It describes exactly what the command changes, what PermLens may do and what to keep in mind in a cluster.

After signing in, PermLens shows **a single command**. Copy it into the **shell of the Proxmox host** (Proxmox web interface → node → *>_ Shell*) and press Enter. It shows three steps (its messages are in German):

1. **Install the guard script** (*Wächter-Script installieren*): `/usr/local/sbin/permlens-guard`. It checks every command from PermLens and only lets allowed ones through.
2. **Allow PermLens' key** (*Schlüssel von PermLens erlauben*): one additional line in `/root/.ssh/authorized_keys`, bound to the guard script and to the address of the PermLens LXC. Nothing is deleted or overwritten.
3. **Report back to PermLens** (*PermLens Bescheid geben*): address, SSH port and host key of the Proxmox host.

PermLens then tests the connection, scans all containers and VMs and jumps to the overview in the browser by itself. **Done.**

You don't have to enter the LXC's number or address anywhere; PermLens and the command find both themselves. The command only runs its script if the checksum matches. It contains a one-time code and is valid for one hour and for one setup only.

Everything PermLens calls on the host is recorded in the system log: `journalctl -t permlens`.

**Another Proxmox host:** under *Settings → Proxmox*, “Add another Proxmox …” shows a new command. Run on the other Proxmox host, it is added to the list. You choose which host you are looking at below the header.

## 6. Allow changes (optional)

Up to here PermLens only **reads**. If PermLens should also change users, groups and permissions inside containers, create a file on the Proxmox host listing the allowed container IDs, e.g.:

```bash
mkdir -p /etc/permlens && echo '105,110-112' > /etc/permlens/schreiben-erlaubt
```

All other containers stay read-only. Delete the file and PermLens immediately goes back to read-only. More: [AENDERN.en.md](AENDERN.en.md) and [SICHERHEIT.en.md, section 3](SICHERHEIT.en.md#3-writing-from-guard-script-version-4).

## Settings in the stack file

| Entry | Meaning |
|---|---|
| `APP_PASSWORD` | **Required**, at least 8 characters. In Dockhand as a stack variable, not in the file itself. Without a password PermLens only shows a notice. A new password signs everyone out. Forgot the password: enter a new value in Dockhand and restart the stack. |
| `ALLOW_PUBLIC=0` | Only access from the home network (default). Do not change. |
| `HTTPS_PORT` | Port under which HTTPS is reachable from outside (`443` or `8443`). If set, PermLens redirects unencrypted requests to HTTPS. |
| `HTTPS=0` | Turns HTTPS off. Only if your own proxy in front handles encryption (at your own risk, see [SICHERHEIT.en.md, section 6](SICHERHEIT.en.md#6-limits-you-should-know-about)). |
| `TZ=Europe/Berlin` | Time zone for display. |
| `UPDATE_CHECK=0` | Turns the “new version available” notice off completely. PermLens then never asks GitHub. Without this entry it can be switched on and off under *Settings → Updates*. |

**A fixed version instead of `:latest`:** if you want to control updates yourself, put e.g. `ghcr.io/luro611/permlens:1.0.0` in the stack file and change the number with every update.

## If something does not work

| What you see | What helps |
|---|---|
| The page does not load | Is the container running? `docker ps` and `docker logs permlens` in the LXC. Are address and port right (`8443` with `https://`)? |
| PermLens only shows a notice about the password | `APP_PASSWORD` is missing or shorter than 8 characters. Add it under the stack's variables in Dockhand, *Redeploy*. |
| “Befehl abgelaufen oder unterwegs verändert, nichts ausgeführt.” (command expired or altered) | The one-time code is older than an hour or already used. Reload the page in PermLens and use the new command. |
| “Bitte als root ausführen” (please run as root) | Open the shell via the Proxmox web interface (node → *>_ Shell*), you are root there. |
| “Das ist kein Proxmox-Host (pct fehlt).” (not a Proxmox host) | The command belongs in the shell of the **Proxmox node**, not in a container's console. |
| “Ungültige Adresse” (invalid address) | Open PermLens via its IP address or a simple name (not through a proxy) and get the command again. |
| “The Proxmox host does not answer” | Can the PermLens LXC reach the Proxmox host on its SSH port? Is there a firewall in between? Does the LXC still have the IP address it was set up with? Otherwise *Settings → Set up again*. |

## What next?

- [User manual](MANUAL.md): the interface and the four tasks step by step.
- [Operations](BETRIEB.md) (German): installing a new version, backup, removal. Your browser's translate function works fine there.
- [Security](SICHERHEIT.en.md): what PermLens may do on the Proxmox host, firewall, limits.
