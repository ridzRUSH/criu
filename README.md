# Live Migration with CRIU

Moving running workloads between two Ubuntu VMs while keeping their in-memory state. Each experiment builds on the previous one, from a single process up to a Kubernetes pod with two containers.

| # | Experiment | What moves | Tools | Status |
| --- | --- | --- | --- | --- |
| 1 | [Process migration](criu_live_migration_of_process/Walk_through.md) | One Python process | CRIU | Done |
| 2 | [Container migration](podman_container_migration/Walk_through.md) | One Podman container | Podman + CRIU | Done |
| 3 | [Single-container pod migration](k3s_single_container_pod_migration/Walk_through.md) | One Kubernetes pod, one container | K3s + CRI-O + CRIU | Done |
| 4 | [Multi-container pod migration](k3s_multi_container_pod_migration/Walk_through.md) | One Kubernetes pod, two containers | K3s + CRI-O + CRIU | Done |

Each experiment folder contains:

- `Walk_through.md`: what was done, why each step is needed, and the problems hit along the way.
- `commands.txt`: the commands to run the experiment again, in order, with the machine for each block.
- `programs/`: the app and config files used.

Experiment 1 has no `commands.txt`; its commands are in its walkthrough.

## Machines

| Name | Role | Address |
| --- | --- | --- |
| vm2 | Source. Also the K3s server in experiments 3 and 4. | 192.168.56.102 |
| vm1 (K3s node `infra-demo`) | Destination | 192.168.56.101 |

Both are VirtualBox VMs on a host-only network.

## Rules that apply to every experiment

- **The destination needs the exact base files.** CRIU saves a process's state, not the program or image it came from. Experiment 1 needed matching paths, users and libraries. Experiments 2 to 4 need the same container image ID on both machines.
- **AppArmor must be off for the migrated workload.** CRIU re-applies the recorded AppArmor profile on restore, and that crashed it here. Set it to unconfined when the container or pod is created.
- **Use root.** Run CRIU, Podman, `crictl` and `buildah` with `sudo`.
- **What doesn't move:** volumes, open TCP connections (unless requested), and, in Kubernetes, the pod object and its IP address.
