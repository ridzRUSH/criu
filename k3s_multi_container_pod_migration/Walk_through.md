# Multi-Container Pod Migration with K3s, CRI-O and CRIU (vm2 → infra-demo)

## What this experiment does

A pod with two containers, a Flask app and Redis, is checkpointed on node **vm2** and restored on node **infra-demo** (VM1). Both processes resume with their in-memory state, and Flask can still reach Redis inside the new pod.

It extends the single-container experiment in [`../k3s_single_container_pod_migration`](../k3s_single_container_pod_migration/Walk_through.md), which also documents the cluster setup used here. The new questions are:

1. Can CRI-O restore two checkpointed containers into one pod?
2. Do the two containers still work together afterwards?

**Result:** the experiment was completed on 3 November 2026. These "before" values were recorded on vm2:

| Value | Before (2 Nov 2026) |
| --- | --- |
| `counter` | 21 |
| `redis_hits` | 21 |
| `redis_log_len` | 21 |
| `boot_id` (Flask) | `7315860f4f07424fab856c38509dbabd` |
| `run_id` (Redis) | `fcceeca4606656a4b6497a444274ee38aac80182` |

The "after" values weren't saved in this repo. [`commands.txt`](commands.txt) saves both sets to files on the next run.

---

## Environment

Same cluster as the single-container experiment:

| | vm2 (source) | infra-demo (destination) |
| --- | --- | --- |
| Address | 192.168.56.102 | 192.168.56.101 |
| K3s role | Server and worker | Agent |
| Runtime | CRI-O 1.36.3, crun, CRIU 4.2 | CRI-O 1.36.3, crun, CRIU 4.2 |

All `kubectl` commands run on vm2.

---

## How it works

```
                 vm2 (source)                                infra-demo (destination)

  build flask-redis, pull redis ───── save / scp / load ────► same base images (same IDs)
          │
  pod state-demo: [redis] [flask]
          │
  quiet the pod (no traffic, no open connections)
          │
  checkpoint flask ──┐
  checkpoint redis ──┴─ two archives ──────── scp ──────────► build two carrier images
          │                                                          │
  delete source pod ──────── restore YAML (apply) ─────────► CRI-O + CRIU restore both
                                                                     │
                                                       pod state-demo: [redis] [flask]
```

Kubernetes checkpoints **one container per call**. There's no whole-pod checkpoint. A two-container pod therefore needs two checkpoint calls, two archives and two carrier images. One restore YAML then lists both carriers.

---

## The application

Every value that counts lives in memory, so matching values after the restore can only have come from the checkpoints.

| Container | State | How it's checked |
| --- | --- | --- |
| Flask (`localhost/flask-redis`) | `counter` in memory, plus a random `boot_id` from process start | `/peek` |
| Redis (`redis:7-alpine`) | Keys `hits` and `log` in memory, plus Redis's own random `run_id` | `/peek` and `redis-cli INFO server` |

`/` changes the state, while `/peek` only reads it.

### Design choices, and why

| Choice | Why |
| --- | --- |
| Flask opens and closes its Redis connection on every request | CRIU won't dump an open TCP connection by default, and the kubelet checkpoint call can't ask it to. Closing after each request leaves nothing open at checkpoint time. |
| Redis runs with `--save ""` and `--appendonly no` | Turns off disk saving, so Redis's data exists only in memory. It also avoids Redis forking a background save process during a checkpoint. |
| Redis binds `127.0.0.1` | Containers in a pod share one network, so Flask reaches Redis on localhost. Nothing outside the pod needs Redis. |
| `boot_id` and `run_id` instead of PID | Both apps are PID 1 inside their containers, so PIDs would match even after a fresh start. Random IDs created at startup can't. |
| `debug=False`, `threaded=False` in Flask | Keeps Flask to one simple process, which is easier to checkpoint |

---

## Why the pod must be quiet before the checkpoint

The two checkpoints are taken at different moments. In this run they were 1 minute 50 seconds apart. If the containers were exchanging data in between, Flask's saved memory could describe a Redis state that Redis's own checkpoint doesn't match.

The fix is to make sure nothing is changing:

1. Stop sending requests.
2. Check Redis has no client except the check itself:

```bash
sudo kubectl exec -n migration-demo state-demo -c redis -- redis-cli CLIENT LIST
```

Exactly one line, showing `cmd=client|list`, means Flask has no open connection. With no traffic and no background work, neither container changes between the two checkpoints, so their order doesn't matter.

### Why the pod spec can't give a dependency order

Kubernetes YAML has no field saying "Flask depends on Redis". Here the link is `127.0.0.1:6379` inside `app.py`, which Kubernetes never sees. The order of the `containers` list is only a start order, and the kubelet doesn't wait between them.

Making the pod quiet removes the need to know the order at checkpoint time. Pods that can't be made quiet would need the order declared, for example with an annotation, or discovered by watching connections. That isn't covered by this experiment.

---

## Steps, and why each one is needed

The exact commands are in [`commands.txt`](commands.txt).

| Step | What | Why |
| --- | --- | --- |
| 1 | Reset the namespace | The same pod name is reused, and old pods can hold hostPort 8080 |
| 2 | Build `flask-redis` with `--network=host` | The build network can't resolve DNS on these VMs |
| 3 | Copy both base images to infra-demo | Each checkpoint holds only its container's changes. infra-demo needs each base image with the **same ID**. |
| 4 | Deploy `state-demo` on vm2 | Pod-level `appArmorProfile: Unconfined` covers both containers and must be set before checkpointing |
| 5 | Create state and record it | Gives exact values to compare after the restore |
| 6 | Confirm the pod is idle | Makes the two separate checkpoints consistent |
| 7 | Checkpoint `flask`, then `redis` | One `kubectl create --raw` POST per container |
| 8 | Copy both archives to infra-demo | The kubelet writes them readable by root only |
| 9 | Check base images, build two carriers **on infra-demo** | CRI-O only looks for images on its own node |
| 10 | Delete the source, apply the restore YAML | Deleting makes it a migration, not a copy. The restore YAML uses both carrier images. |
| 11 | Verify and save the evidence | The pod can disappear later, so save results straight away |

---

## Problems encountered in this run and solutions

| Problem | Cause | Solution |
| --- | --- | --- |
| `exec [POD] [COMMAND] is not supported anymore` | `--` missing in `kubectl exec` | Put `--` before the command |
| Redis checkpoint printed no `items` line | The terminal output was garbled. CRI-O's log showed both checkpoints succeeded. | Check the archives with `ls`, not the printed output |
| `ErrImageNeverPull` on the restored pod | Carrier images were built on vm2, but the pod runs on infra-demo | Build the carriers on infra-demo |
| `1/2` with `CreateContainerError` | infra-demo didn't have Flask's base image build `f3a714198d556`. vm2 had two builds of `flask-redis`, and infra-demo didn't have the one the checkpoint needed. | Check each checkpoint's `rootfsImageRef` against infra-demo's images, copy the right build, then reapply |
| `docker-archive doesn't support modifying existing images` | An old `/tmp/flask-redis.tar` already existed, possibly holding the older build | `rm -f` the tar before `podman save` |
| `pods "state-demo" not found` the next day | The restored pod was gone. Events suggest a node or API connection was lost, and Kubernetes doesn't recreate a standalone pod. | Apply the restore YAML again. The carriers still hold the same checkpoint. |
| `sudo: timed out` | Password prompt left unanswered | Run again and enter the password |
| `kubectl` on infra-demo: `localhost:8080 refused` | infra-demo has no cluster login | Run `kubectl` on vm2 |
| CRI-O log search on infra-demo came back empty | The search pattern didn't match how the error was logged | Read the pod's container status first (see `commands.txt`) |

**Lesson:** if you rebuild `flask-redis` on vm2, copy it to infra-demo again before checkpointing. A checkpoint needs the exact build its container started from.

---

## What a successful run proves, and what it doesn't

**Proves**, for this pod in this run: two containers in one pod were restored on another node, with their in-memory state and process identity intact, and they still worked together.

**Doesn't prove:**

- **Downtime:** this run spanned hours of troubleshooting, so it gives no downtime figure.
- **Pods under load:** the pod was idle at checkpoint time.
- **Open connections:** the app was designed to have none.
- **Volumes:** none were used. Volume contents aren't included in a checkpoint.
- **Repeatability:** this is one trial of one workload.
- **Cluster identity:** the pod object and pod IP are recreated, not moved.
