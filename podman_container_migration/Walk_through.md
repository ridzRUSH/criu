# Podman Container Migration with CRIU (vm2 → vm1)

## What this experiment does

A running container is checkpointed with Podman on **vm2**, moved as one archive, and restored on **vm1**. The container runs a small Node.js server whose request counter lives only in memory.

If the restored container continues counting instead of starting again from 1, its memory moved with it.

**Result:** in the successful run, the counter read `{"cnt":4}` on vm2 before the checkpoint and `{"cnt":6}` on vm1 after two requests. Every request to `/` adds one, so 6 is the expected next value after two requests, not an error.

---

## Why Podman instead of Docker

Docker was tried first and abandoned. Its restore failed with:

```
bind-mount /proc/0/ns/net -> /var/run/docker/netns/...: no such file or directory
```

| | Docker | Podman |
| --- | --- | --- |
| Checkpoint support | Experimental | Built in (`podman container checkpoint`) |
| Moving to another host | Not reliable | `--export` and `--import` produce and consume one portable archive |
| Daemon | Needs `dockerd` | Daemonless |

Podman's checkpoint code is also shared with CRI-O, which the later Kubernetes experiments use. Lessons from this experiment carry over.

---

## Environment

| | vm2 (source) | vm1 (destination) |
| --- | --- | --- |
| Address | 192.168.56.102 | 192.168.56.101 |
| OS | Ubuntu | Ubuntu |
| Tools | Podman 5.7, CRIU | Podman 5.7, CRIU |
| App folder | `~/Desktop/node-ser` | not needed |

The VMs talk over a VirtualBox host-only network.

---

## How it works

```
            vm2 (source)                              vm1 (destination)

   podman build  ──► image ──── save / scp / load ───► same image (same ID)
        │
   podman run  ──► running container
        │
   podman container checkpoint --export
        │   CRIU freezes the process and saves
        │   memory, open files and sockets
        ▼
   node-demo.tar.gz ─────────── scp ──────────────────► podman container restore --import
                                                             │
                                                             ▼
                                                     process continues running
```

The exported archive holds three things:

1. CRIU's dump of the process: memory pages, registers, open files and sockets.
2. The container's configuration.
3. The filesystem **changes** made inside the container.

It does **not** hold the base image. vm1 must already have the exact same image, with the same image ID, before restoring. That is why the image is copied with `podman save` and `podman load` instead of being rebuilt on vm1. A rebuild gets a different ID, and the restore refuses it.

---

## The application

The state is a counter in memory. Nothing is written to disk.

`programs/server.js`:

```javascript
const express = require("express");
const app = express();
let cnt = 0;

app.get("/", (req, res) => {
    cnt++;
    res.json({ cnt });
});

app.listen(8080, "0.0.0.0", () => {
    console.log("Listening on port 8080");
});
```

`programs/package.json` declares `express`, and `programs/Dockerfile` builds it on `node:22-alpine`.

An earlier attempt used nginx. Nginx proves the container restarts, but it holds no visible state, so it can't show that memory survived. The counter can.

---

## Steps, and why each one is needed

The exact commands are in [`commands.txt`](commands.txt).

### 1. Allow short image names

```
Error: short-name "node:22-alpine" did not resolve to an alias
```

Podman refuses to guess which registry a short name like `node:22-alpine` comes from. Adding `unqualified-search-registries = ["docker.io"]` at the top of `/etc/containers/registries.conf` tells it to use Docker Hub.

### 2. Build with `--network=host`

`npm install` failed inside the build with `getaddrinfo EAI_AGAIN registry.npmjs.org`. The same failure happened on two different upstream networks, so the DNS servers weren't the problem. The problem was the isolated network Podman creates for each build step.

`--network=host` makes the build use vm2's own network, which already resolves DNS correctly.

### 3. Use `sudo podman` everywhere

Podman keeps two separate container stores:

| Mode | Store |
| --- | --- |
| Rootless (`podman`) | `~/.local/share/containers` |
| Rootful (`sudo podman`) | `/var/lib/containers` |

A container started with `podman` can't be checkpointed with `sudo podman`, which reports `no container found`. Checkpointing also needs root privileges. Rootless Podman didn't work on these VMs at all (`cannot clone: Permission denied`), so every command uses `sudo`.

### 4. Copy the image to vm1

`podman save` writes the image to a tar file, `scp` copies it, and `podman load` imports it on vm1 with its ID unchanged. Delete the old tar first, because `podman save` refuses to overwrite an existing file.

### 5. Run the container with AppArmor unconfined

```bash
sudo podman run -d --name node-demo --security-opt apparmor=unconfined -p 8080:8080 localhost/checkpoint-demo:latest
```

CRIU records the process's AppArmor profile and tries to re-apply it on restore. Here that step crashed CRIU:

```
restoring lsm profile
changeprofile containers-default
can't write lsm profile
Segmentation fault
```

Starting the container with no AppArmor profile leaves nothing for CRIU to re-apply. This affects only this container, unlike disabling AppArmor for the whole machine with the `apparmor=0` kernel parameter.

### 6. Create state

Send a few requests and note the last `cnt` value. Every request to `/` increments the counter, including requests you make only to check it.

### 7. Checkpoint

```bash
sudo podman container checkpoint --export=/tmp/node-demo.tar.gz --tcp-established node-demo
```

| Option | Why |
| --- | --- |
| `--export=...` | Writes everything to one archive that can be copied to another host. |
| `--tcp-established` | Lets CRIU save open TCP connections, which it otherwise refuses to dump. |

Podman **stops** the container after a checkpoint by default. Kubernetes, in the later experiments, does the opposite.

### 8. Copy the archive and restore on vm1

```bash
sudo podman container restore --import=/tmp/node-demo.tar.gz --tcp-established
```

Before restoring, remove any leftover `node-demo` container. A failed or interrupted restore leaves runtime state behind, and the next attempt then reports `container init still running` or a creation timeout.

### 9. Verify

Request `/` on vm1. The value should continue from where vm2 stopped. If you sent requests in between, the number grows by one for each of them.

---

## Problems encountered and solutions

| Problem | Cause | Solution |
| --- | --- | --- |
| Docker restore: `bind-mount /proc/0/ns/net` | Docker's checkpoint support is experimental | Use Podman |
| `short-name ... did not resolve to an alias` | No default registry configured | Add `unqualified-search-registries` |
| `EAI_AGAIN registry.npmjs.org` during build | The build's isolated network couldn't resolve DNS | `podman build --network=host` |
| `nameserver 127.0.0.53` in `/etc/resolv.conf` | systemd-resolved's local stub, which containers can't reach | Not the final fix, but noted: pointing `/etc/resolv.conf` at `/run/systemd/resolve/resolv.conf` exposes the real servers |
| `Too many DNS servers configured` | Only the first three `nameserver` lines are used | Not the final fix either; `--network=host` avoided the issue |
| `no container found` on checkpoint | Container created rootless, checkpoint run rootful | Use `sudo podman` for everything |
| `cannot clone: Permission denied` | Rootless Podman can't create user namespaces on these VMs | Use rootful Podman |
| `Segmentation fault` at `changeprofile containers-default` | CRIU re-applying the AppArmor profile | `--security-opt apparmor=unconfined` at `podman run` |
| Restore stuck, `criu restore` still running | A previous restore never finished | `sudo podman rm -f node-demo` and `sudo podman container cleanup -a`, then retry |
| `docker-archive doesn't support modifying existing images` | The `podman save` output file already exists | Delete it first |
| `sudo: a terminal is required to authenticate` | `ssh host 'sudo ...'` gives sudo no terminal for the password | Use `ssh -t` |
| `curl localhost:8080` reset on vm2, while `podman exec ... wget` inside worked | Host-to-container networking problem, not the app | Check from inside with `podman exec`; the app itself was healthy |
| Counter 2 higher than expected after restore | Each check request to `/` also increments it | Expected; count your requests |

---

## Requirements for a successful migration

- **Same image ID** on both machines.
- **Rootful Podman** on both machines.
- **AppArmor unconfined** for the container, set at `podman run`.
- **Compatible CRIU and kernel** on both machines.
- **Port 8080 free** on vm1.
