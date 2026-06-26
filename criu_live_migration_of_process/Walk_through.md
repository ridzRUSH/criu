
```markdown
# CRIU Process Migration (vm2 → vm1)

## Project Overview

This project demonstrates **live process migration** using **CRIU (Checkpoint/Restore In Userspace)**.

A running Python process (`monti_carlo.py`) is checkpointed on one machine (**vm2**) and restored on another machine (**vm1**) using CRIU.

The goal is to migrate a running application with its memory state, execution state, open files, and environment without restarting the application.

---

# Architecture

```

```
            Source Machine
                vm2

    Running Python Process
            |
            |
      CRIU checkpoint
            |
            |
         dump/
            |
            |
      Transfer dump files
            |
            v

            Destination Machine
                vm1

      CRIU restore
            |
            |
    Process continues running
```

```

---

# Environment

## Source Machine

```

Hostname: vm2
OS: Ubuntu
Kernel: Linux 7.0.0-22-generic
Architecture: x86_64
User: vm2

```

Process location:

```

/home/vm2/Desktop/criu

```

Application:

```

monti_carlo.py

```

---

## Destination Machine

```

Hostname: vm1
OS: Ubuntu
Kernel: Linux 7.0.0-22-generic
Architecture: x86_64

```

Required environment:

```

User: vm2
Directory: /home/vm2/Desktop/criu

```

---

# Application

The migrated application is a Monte Carlo Pi calculation program.

Example:

```

monti_carlo.py

````

The program continuously calculates Pi using random points.

The process is checkpointed while running and restored on another machine.

---

# Installing CRIU

Install CRIU on both machines:

```bash
sudo apt update
sudo apt install criu
````

Check installation:

```bash
criu check
```

If running without root:

```bash
criu check --unprivileged
```

For full functionality use:

```bash
sudo criu check
```

---

# Step 1: Run Application on vm2

Start the Python program:

```bash
python3 monti_carlo.py
```

Find the PID:

```bash
ps aux | grep python
```

Example:

```
PID = 8937
```

---

# Step 2: Create CRIU Checkpoint on vm2

Create dump directory:

```bash
mkdir dump
```

Checkpoint the process:

```bash
sudo criu dump \
-t 8937 \
-D dump \
--shell-job
```

Explanation:

| Option      | Meaning                |
| ----------- | ---------------------- |
| dump        | Create checkpoint      |
| -t PID      | Target process         |
| -D dump     | Store checkpoint files |
| --shell-job | Allow shell processes  |

---

# Step 3: Transfer Dump to vm1

Copy checkpoint directory:

Example:

```bash
scp -r dump vm1@192.168.56.101:/home/vm1/
```

The dump contains:

```
memory state
process information
file descriptors
CPU state
namespace information
```

---

# Step 4: Prepare Destination Machine

CRIU requires the destination environment to match the source.

## Create required directory

On vm1:

```bash
sudo mkdir -p /home/vm2/Desktop/criu
```

---

## Match permissions

Original permission:

```
775
```

Set:

```bash
sudo chmod 775 /home/vm2/Desktop/criu
```

---

## Create user

The source process belonged to user `vm2`.

Create the same user:

```bash
sudo useradd -m vm2
```

Set ownership:

```bash
sudo chown -R vm2:vm2 /home/vm2/Desktop/criu
```

---

# Step 5: Fix Library Differences

During restore, CRIU checks files used by the process.

Example error:

```
File usr/lib/locale/locale-archive has bad size
```

Reason:

Source:

```
vm2:
locale-archive = 14MB
```

Destination:

```
vm1:
locale-archive = 3MB
```

Solution:

Copy the file:

On vm2:

```bash
scp /usr/lib/locale/locale-archive \
vm1@192.168.56.101:/tmp/
```

On vm1:

```bash
sudo cp /tmp/locale-archive \
/usr/lib/locale/locale-archive
```

Verify:

```bash
ls -lh /usr/lib/locale/locale-archive
```

Both machines should match.

---

# Step 6: Restore Process on vm1

Restore:

```bash
sudo criu restore \
-D /home/vm1/dump \
--shell-job
```

---

# Verification

Check restored process:

```bash
ps -ef | grep python
```

Example:

Before migration:

```
vm2
PID 8937
python3 monti_carlo.py
```

After restore:

```
vm1
PID 6346
python3 monti_carlo.py
```

PID changes are expected.

The process state is restored.

---

# Problems Encountered and Solutions

## 1. CRIU Permission Error

Error:

```
CRIU needs CAP_SYS_ADMIN
```

Cause:

CRIU requires kernel privileges.

Solution:

Run:

```bash
sudo criu dump
```

---

## 2. Missing Dump Directory

Error:

```
Can't open dir /dump
```

Cause:

Directory did not exist.

Solution:

Create:

```bash
mkdir dump
```

---

## 3. Locale Archive Size Mismatch

Error:

```
locale-archive has bad size
```

Cause:

Different system libraries.

Solution:

Copy matching locale archive.

---

## 4. Missing Working Directory

Error:

```
Can't open cwd
```

Cause:

Original process directory did not exist.

Solution:

Create:

```
/home/vm2/Desktop/criu
```

---

## 5. Directory Permission Mismatch

Error:

```
bad mode 040755
expect 040775
```

Cause:

Different directory permissions.

Solution:

```bash
chmod 775 directory
```

---

## 6. Bash Prompt Errors

Error:

```
bad substitution
systemd_exitstatus
```

Cause:

Broken bash configuration.

Solution:

Use clean shell:

```bash
/bin/bash --noprofile --norc
```

Restore bash configuration:

```bash
cp /etc/skel/.bashrc ~/.bashrc
```

---

# Important CRIU Requirements

For successful migration:

## Kernel

Both machines should have compatible kernels.

Example:

```
Linux 7.0.0-22-generic
```

---

## CPU Architecture

Must match:

```
x86_64 → x86_64
```

---

## Filesystem

Paths must exist:

Source:

```
/home/vm2/Desktop/criu
```

Destination:

```
/home/vm2/Desktop/criu
```

---

## Libraries

Shared libraries must match:

Examples:

```
glibc
locale files
system libraries
```

---

## Users

Same user should exist:

```
vm2
```

---

## Permissions

File permissions must match.

Example:

```
775 != 755
```

---

# Conclusion

CRIU successfully demonstrates process migration by moving a running process from vm2 to vm1.

The main challenge is that CRIU restores the complete execution environment, not just the program.

Successful migration requires:

```
Same Kernel
Same Architecture
Same Libraries
Same Paths
Same Permissions
Same Users
Complete Dump Files
```

When these conditions are satisfied, a running process can be checkpointed on one machine and resumed on another machine without restarting.

````