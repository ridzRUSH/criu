# Single-Container Pod Migration with K3s, CRI-O and CRIU (vm2 → infra-demo)

## What this experiment does

A Kubernetes pod running a Flask counter is checkpointed on node **vm2** and restored on node **infra-demo** (VM1). The process resumes with its in-memory counter, instead of starting again.

This is the Kubernetes version of the Podman experiment in [`../podman_container_migration`](../podman_container_migration/Walk_through.md). Podman does the checkpoint and restore itself. Here, Kubernetes has to ask the container runtime to do it, and Kubernetes has no restore command, so a workaround is needed.

**Result:** the migration was completed on 10 October 2026. The before and after values weren't saved in this repo, so record them on the next run. [`commands.txt`](commands.txt) saves them to a file.

---

## Environment

| | vm2 (source) | infra-demo (destination) |
| --- | --- | --- |
| Address | 192.168.56.102 | 192.168.56.101 |
| K3s role | Server (control plane) and worker | Agent (worker) |
| K3s version | v1.36.2+k3s1 | v1.36.3+k3s1 |
| Container runtime | CRI-O 1.36.3 | CRI-O 1.36.3 |
| Low-level runtime | crun | crun |
| CRIU | 4.2 | 4.2 |
| Pod network | 10.42.0.0/24 | 10.42.1.0/24 |

The Kubernetes API server runs only on vm2, so **every `kubectl` command runs on vm2**. On infra-demo, `kubectl` fails with `connection to the server localhost:8080 was refused`.

---

## Why the stack is built this way

```
kubectl / kubelet          asks for a checkpoint
        │
        ▼
CRI (Kubernetes ↔ runtime contract)   has CheckpointContainer, but no RestoreContainer
        │
        ▼
CRI-O                      restores when a pod uses a specially marked image
        │
        ▼
crun                       low-level runtime, calls CRIU
        │
        ▼
CRIU                       freezes, saves and rebuilds the process
```

### Why CRI-O instead of K3s's default containerd

The Container Runtime Interface (CRI) has a `CheckpointContainer` call but no restore call. There's no `kubectl restore`.

CRI-O works around this. When a pod uses an image carrying the annotation `io.kubernetes.cri-o.annotations.checkpoint.name`, CRI-O restores the checkpoint inside that image instead of starting a fresh container.

containerd, K3s's default runtime, has no built-in equivalent. Restoring a checkpoint through Kubernetes on containerd needs extra components: the [checkpoint-restore-operator](https://github.com/checkpoint-restore/checkpoint-restore-operator) adds a `PodRestore` resource and a CRI proxy that sits between the kubelet and containerd. A related project, [Distributed-Process-Migration-using-CRIU](https://github.com/garvagrawal9084/Distributed-Process-Migration-using-CRIU), used that route.

CRI-O was chosen because it restores natively, with nothing extra to install, run or keep version-compatible. On a two-VM testbed, fewer moving parts also made failures easier to trace.

CRI-O also shares its checkpoint code and its image store (`/var/lib/containers/storage`) with rootful Podman. An image loaded with `sudo podman load` is visible to CRI-O immediately, so no image registry is needed.

---

## Cluster setup

Both Kubernetes experiments use this cluster. The exact CRI-O and K3s install commands weren't saved, but these are the settings that made the cluster work.

| Setting | Where | Why |
| --- | --- | --- |
| K3s uses CRI-O | K3s service on both nodes, `--container-runtime-endpoint unix:///var/run/crio/crio.sock` | Replaces containerd with CRI-O |
| `enable_criu_support = true` | CRI-O config on both nodes | Lets CRI-O call CRIU |
| `crun` installed | Both nodes | The checkpoint records `crun` as its runtime. infra-demo was missing it at first. |
| `--node-ip 192.168.56.10x` | K3s systemd override, **only** there | Each node advertises its host-only address |
| `flannel-iface: enp0s8` | `/etc/rancher/k3s/config.yaml` | Pod traffic uses the host-only network |
| UFW routed rule | infra-demo (and vm2 if UFW is active) | Lets pod-to-pod traffic cross nodes |
| UFW UDP 8472 on `enp0s8` | infra-demo (and vm2 if UFW is active) | Lets Flannel's VXLAN tunnel through |

### Why each network setting was needed

- **Both VMs have the NAT address 10.0.2.15.** Flannel first picked it on infra-demo. Both nodes then showed `Ready`, but pods on different nodes couldn't reach each other. `flannel-iface: enp0s8` forces the host-only network.
- **`node-ip` set twice broke K3s.** With it in both the systemd override and `config.yaml`, K3s built `--node-ip=192.168.56.101,192.168.56.101` and refused to start. Keep each setting in one place.
- **UFW blocked routed traffic.** infra-demo had UFW with `Default: deny (routed)`. Packet capture showed VXLAN packets arriving, yet pod traffic still timed out. Allowing routed traffic for `10.42.0.0/16` fixed it.

Before any migration, two nginx pods (one per node) were used to prove cross-node pod networking worked (`HTTP/1.1 200 OK`). That way a later failure points at the migration, not the network.

---

## The application

A Flask counter that keeps its state only in memory. See `programs/app.py`.

| Endpoint | What it does |
| --- | --- |
| `/` | Adds one to the counter and returns it |
| `/peek` | Returns the counter **without** changing it |

The response also includes:

- `boot_id`: a random ID created when the process starts. A fresh start gets a new one, and a restore keeps the old one.
- `pid` and `host`: shown for interest. The app is PID 1 inside its container, so the PID would also be 1 after a fresh start. It isn't evidence on its own.

`boot_id` was added after the original run, once it was clear PID couldn't tell a restore from a fresh start.

The app runs with `debug=False` and `threaded=False`. Debug mode starts a second reloader process, which complicates the checkpoint. A production server such as gunicorn would also fork extra processes, so the plain development server is the right choice here.

---

## Steps, and why each one is needed

The exact commands are in [`commands.txt`](commands.txt).

### 1. Build the image and copy it to infra-demo

The checkpoint holds only the container's filesystem **changes**, not the base image. infra-demo needs the same image with the same image ID. `podman save` and `podman load` keep the ID. Rebuilding on infra-demo would give a new ID, and the restore would fail.

The build uses `--network=host` because Podman's build network couldn't resolve DNS on these VMs.

### 2. Deploy the pod on vm2

| Setting | Why |
| --- | --- |
| `nodeName: vm2` | Puts the pod on the source node, so the scheduler can't choose another |
| `restartPolicy: Never` | A failed container stays failed, so a failure can't look like a success |
| `appArmorProfile: Unconfined` | CRIU records the AppArmor profile and re-applies it on restore, which crashed CRIU earlier. It must be set **before** the checkpoint. |
| `imagePullPolicy: Never` | `localhost/` images can't be downloaded, so the kubelet must use the local copy |
| `hostPort: 8080` | Reach the app at the node's address, so you can see it move from .102 to .101 |

### 3. Create state and record it

Send requests to `/`, then read the values with `/peek`. After recording, send no more requests to `/`, because the checkpoint below doesn't stop the container.

### 4. Checkpoint

```bash
sudo kubectl create --raw "/api/v1/nodes/vm2/proxy/checkpoint/migration-demo/flask-counter/flask-container" -f /dev/null
```

| Part | Why |
| --- | --- |
| `kubectl create --raw` | Sends a **POST**. The checkpoint endpoint rejects GET, so `kubectl get --raw` doesn't work. |
| `/api/v1/nodes/vm2/proxy/` | Goes through the API server to the kubelet on vm2, using your normal `kubectl` login |
| `.../migration-demo/flask-counter/flask-container` | Namespace, pod, then **container** name |
| `-f /dev/null` | `--raw` needs a file for the request body, and this one is empty |

The archive appears in `/var/lib/kubelet/checkpoints/` as `checkpoint-<pod>_<namespace>-<container>-<time>.tar`.

**Kubernetes leaves the source container running** after a checkpoint, because the feature was designed for forensic snapshots. Podman stops it. So the source pod must be deleted later, or the result is a copy rather than a migration.

### 5. Copy the archive to infra-demo

The kubelet writes the archive readable by root only, so it is copied to `/tmp` and given read permission before `scp`.

### 6. Build the carrier image on infra-demo

```bash
NC=$(sudo buildah from scratch)
sudo buildah add "$NC" /tmp/ckpt-flask.tar /
sudo buildah config --annotation=io.kubernetes.cri-o.annotations.checkpoint.name=flask-container "$NC"
sudo buildah commit "$NC" localhost/flask-checkpoint:latest
sudo buildah rm "$NC"
```

| Part | Why |
| --- | --- |
| `from scratch` | Starts an empty image. It holds only the checkpoint and has no app, so it can't start normally. |
| `add ... /` | Puts the checkpoint inside the image |
| `--annotation=...checkpoint.name=flask-container` | Marks the image as a checkpoint. Use the container's name. |
| `commit` | Saves it into the store that CRI-O reads |

Build it **on infra-demo**, because the restored pod runs there and CRI-O only looks for images on its own node.

### 7. Delete the source pod and restore on infra-demo

The restore YAML is an ordinary pod with the same name, `nodeName: infra-demo`, and the carrier image. CRI-O sees the annotation and uses CRIU to restore the process instead of starting it fresh. Using the same pod name means `kubectl get pod flask-counter -o wide` shows one pod whose node changed.

### 8. Verify

| Result | Expected | What it shows |
| --- | --- | --- |
| Node | `infra-demo` | The workload moved |
| Pod IP | Changed, `10.42.0.x` → `10.42.1.x` | The new pod has a new network. This is expected. |
| `counter` | Same as before the checkpoint | Flask's memory survived |
| `boot_id` | Same as before | It's the original process, not a fresh start |

---

## What moves and what doesn't

| Moves | Doesn't move |
| --- | --- |
| Process memory, including the counter | The pod object, which is deleted and recreated |
| Open files and listening sockets | The pod IP |
| The container's filesystem changes | Volumes, which aren't included in the checkpoint |
| The process's execution point | Open TCP connections, because the kubelet call can't request them |

---

## Problems encountered and solutions

| Problem | Cause | Solution |
| --- | --- | --- |
| Both nodes `Ready`, but pods couldn't reach pods on the other node | Flannel used the duplicated NAT address 10.0.2.15 | `flannel-iface: enp0s8` |
| `bad --node-ip "192.168.56.101,192.168.56.101"` | `node-ip` set in two places | Keep it only in the systemd override |
| VXLAN packets arrive but pod traffic times out | UFW `Default: deny (routed)` | `ufw route allow from 10.42.0.0/16 to 10.42.0.0/16` and allow UDP 8472 on `enp0s8` |
| `kubectl` on infra-demo: `localhost:8080 refused` | infra-demo has no cluster login | Run `kubectl` on vm2 |
| Checkpoint call gives no output and no archive | `curl -s` hid the error, and the K3s admin certificate path assumed in the command didn't exist | Use `kubectl create --raw` instead of `curl` |
| Checkpoint call returns 404 or 405 | Wrong HTTP method (GET), or the `ContainerCheckpoint` feature gate is off | Use `kubectl create --raw` (POST); check the feature gate |
| `crictl`: permission denied on the socket | `crictl` needs root | Use `sudo crictl` |
| `crictl`: `crio.socket: no such file` | Typing mistake in the path | The socket is `/var/run/crio/crio.sock` |
| Image was tagged `flask-container`, but commands used `flask-counter` | Names didn't match | Use one name everywhere |
| Restored pod stuck `Pending` | An older pod still held hostPort 8080 | Delete the old pod first |
| VM1 was missing `crun` | Not installed with CRI-O | `sudo apt install -y crun`, then restart CRI-O |
