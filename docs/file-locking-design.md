# File Locking Design Decision

## The Problem: Race Conditions

The `ProfileStore` reads a JSON file into memory, modifies it, and writes it back.
If two MCP clients do this simultaneously, one overwrites the other's changes:

```
Client A: reads file        → {name: "John Doe"}
Client B: reads file        → {name: "John Doe"}
Client A: writes file       → {name: "John Doe", location: "New York"}
Client B: writes file       → {name: "John Doe", skill: "Python"}  ← OVERWRITES Client A's change!
```

## Options Considered

### Option 1: OS-Level File Locks (fcntl / msvcrt)

The kernel locks the file descriptor. If the process dies, the kernel automatically
releases the lock. No stale lock problem.

**Good for:**
- Single-machine, multi-process scenarios
- Simplicity and correctness
- When all access goes through file I/O (not networked file systems)

**Bad for:**
- NFS / network drives — OS locks don't reliably work across machines
- Cross-language coordination where some participants might not respect advisory locks

**Design pattern: Advisory Locking**
```
acquire_lock(file)
try:
    read → modify → write
finally:
    release_lock(file)
```

Called "advisory" because the OS doesn't enforce it — any process that doesn't
bother locking can still write. All participants must cooperate.

### Option 2: Lock Files (.lock / .pid files)

Create a separate sentinel file. Its existence means "locked." Delete when done.

**Good for:**
- Cross-machine locking (NFS, shared drives, S3)
- Cross-language coordination (Python and Node both understand "does this file exist?")
- Visibility — you can `ls` and see the lock
- Simple scripts, cron jobs, deployment tools

**Bad for:**
- Stale locks: if the process crashes before deleting the lock file, it stays behind
  and blocks all other processes forever
- High-contention scenarios (polling "does file exist?" is wasteful)

**Stale lock mitigation:** Store the PID inside the lock file. Before waiting, check
if that process is still alive. If not, delete the stale lock. But this introduces
its own race: two processes could both detect the stale lock simultaneously.

**Design pattern: Distributed Mutex**
```
while lock_file_exists():
    if lock_is_stale():
        delete_lock()
        break
    sleep(backoff)
create_lock_file(pid=my_pid)
try:
    do_work()
finally:
    delete_lock_file()
```

Used by package managers (apt, npm), pid files for daemons, etc.

### Option 3: OS Lock + Retry (Exponential Backoff)

OS-level lock, but if someone else holds it, wait and retry with increasing delays.

**Good for:**
- Multiple MCP clients on one machine, occasional concurrent writes
- Any situation where contention is possible but brief
- Correctness and resilience

**Bad for:**
- Overkill for single-process applications
- Real-time systems where you can't afford to wait

**Design pattern: Optimistic Concurrency with Backoff**
```
for attempt in [10ms, 20ms, 40ms, 80ms, 160ms]:
    try:
        acquire_lock(file)
        read → modify → write
        release_lock(file)
        return  # success
    except LockHeld:
        sleep(attempt)
raise TimeoutError("couldn't acquire lock")
```

## Broader Landscape

| Pattern                  | Mechanism                    | Used by                            |
|--------------------------|------------------------------|------------------------------------|
| Advisory file lock       | OS kernel                    | SQLite, pid files                  |
| Lock file                | Sentinel file                | apt, npm, systemd                  |
| Database lock            | Row/table locking            | Postgres, MySQL                    |
| Compare-and-swap         | Atomic CPU instruction       | Redis, concurrent data structures  |
| Optimistic concurrency   | Version number, reject stale | HTTP ETags, DynamoDB               |
| Actor model              | Single writer, message queue | Erlang, Akka                       |

## Decision

**Chosen: Option 3 — OS Lock + Retry with Exponential Backoff**

Rationale:
- Most portable across Windows/Linux/Mac using Python's stdlib
- No stale lock problem (kernel releases on crash)
- Handles brief contention gracefully
- Zero additional dependencies
- Small code footprint (~30 lines)

The actor model (single writer process) would be the most naturally correct
architecture since it eliminates races entirely, but it requires a larger
architectural change. OS lock + retry is the pragmatic choice for v0.1.
