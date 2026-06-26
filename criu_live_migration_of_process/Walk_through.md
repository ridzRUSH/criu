Here is the README content rewritten as a **single section** (no separate chapters), suitable for a project submission:

```markdown
# CRIU Process Migration (vm2 → vm1)

This project demonstrates process migration using **CRIU (Checkpoint/Restore In Userspace)** by moving a running Python application (`monti_carlo.py`) from one Linux machine (**vm2**) to another Linux machine (**vm1**) without restarting the application. CRIU creates a checkpoint of the running process by saving its memory state, CPU state, open files, file descriptors, namespaces, and execution environment into image files. These checkpoint files are then transferred to the destination machine, where CRIU restores the process and continues its execution.

The source machine (vm2) and destination machine (vm1) were running Ubuntu with the same kernel version and architecture:

```

Kernel: Linux 7.0.0-22-generic
Architecture: x86_64

```

The application was running on vm2 from:

```

/home/vm2/Desktop/criu/monti_carlo.py

````

The running process ID was identified using:

```bash
ps aux | grep monti_carlo.py
````

Example:

```
PID = 8937
```

A checkpoint was created on vm2 using:

```bash
sudo criu dump -t 8937 -D dump --shell-job
```

The `dump` command creates a checkpoint of the process, `-t` specifies the target process ID, `-D` specifies the directory where checkpoint images are stored, and `--shell-job` allows CRIU to checkpoint processes attached to a shell.

The generated dump directory was transferred from vm2 to vm1 using SSH/SCP. During the first restore attempt on vm1:

```bash
sudo criu restore -D /home/vm1/dump --shell-job
```

the restore failed because the destination environment was not identical to the source environment.

The first error was:

```
File usr/lib/locale/locale-archive has bad size
expect 14622112
found 3064432
```

This happened because CRIU restores the complete process environment, not only the executable. The Python process had loaded `/usr/lib/locale/locale-archive` into memory on vm2. The file size on vm2 was 14MB, while vm1 had a different 3MB version. Since CRIU detected that the mapped file was different, it could not recreate the memory mapping. The issue was solved by copying the locale archive from vm2 to vm1:

On vm2:

```bash
scp /usr/lib/locale/locale-archive vm1@192.168.56.101:/tmp/
```

On vm1:

```bash
sudo cp /tmp/locale-archive /usr/lib/locale/locale-archive
```

After fixing the library mismatch, the next restore error was:

```
Can't open file home/vm2/Desktop/criu
Can't open cwd
```

This occurred because the original process was running inside the directory:

```
/home/vm2/Desktop/criu
```

CRIU saved the current working directory as part of the checkpoint. During restore, vm1 did not contain this directory, so CRIU could not recreate the process state. The directory was created on vm1:

```bash
sudo mkdir -p /home/vm2/Desktop/criu
```

The next error was:

```
File home/vm2/Desktop/criu has bad mode 040755
expect 040775
```

This happened because CRIU also verifies file permissions. The original directory on vm2 had permission `775`, while the newly created directory had permission `755`. The permission was corrected:

```bash
sudo chmod 775 /home/vm2/Desktop/criu
```

The ownership also needed to match the original machine. The process on vm2 belonged to user `vm2`, so the same user was created on vm1:

```bash
sudo useradd -m vm2
```

The directory ownership was updated:

```bash
sudo chown -R vm2:vm2 /home/vm2/Desktop/criu
```

After these changes, the destination machine had the required environment for restoration:

```
Same kernel
Same architecture
Same libraries
Same filesystem paths
Same permissions
Same user environment
```

The final restore command was:

```bash
sudo criu restore \
-D /home/vm1/dump \
--shell-job
```

After restoration, the process continued running on vm1. The process ID was different because Linux assigns new PIDs on each machine. For example:

Source machine:

```
vm2
PID 8937
python3 monti_carlo.py
```

Destination machine:

```
vm1
PID 6346
python3 monti_carlo.py
```

The PID change is expected because PIDs are managed independently by each Linux kernel. CRIU restores the process state, memory, and execution context, not necessarily the same PID.

During the process, a bash error was also encountered:

```
bad substitution
systemd_exitstatus not a valid identifier
```

This was unrelated to CRIU. It was caused by a corrupted `.bashrc`/shell prompt configuration. A clean shell was used to continue CRIU operations:

```bash
/bin/bash --noprofile --norc
```

For successful CRIU migration, both machines must have a compatible environment. The important requirements are:

* Same CPU architecture (`x86_64 → x86_64`)
* Compatible Linux kernel versions
* Same required libraries and shared objects
* Same filesystem paths used by the process
* Same file permissions
* Same users and groups
* Complete CRIU checkpoint directory

CRIU migration is therefore not simply copying an application. It is migrating the complete runtime state of a process. Any difference in files, paths, permissions, libraries, or users can prevent restoration. Once the destination environment matches the source environment, CRIU can successfully checkpoint a running process on one machine and restore it on another machine.

```

