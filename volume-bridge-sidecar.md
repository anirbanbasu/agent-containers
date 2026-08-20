# Docker volume bridge sidecar

## Background

The hardened agent images in this repository persist their unprivileged user's
home directory in a named Docker volume. That gives the agent a writable,
persistent home while the rest of its root filesystem stays read-only, exactly
as [the containment philosophy](docs/containment-philosophy.md) intends.

The cost of that design lands on the host: a named volume's data is not easily
reachable by an ordinary, unprivileged process on the host.

- On **Linux**, the volume is a real directory
  (`/var/lib/docker/volumes/<name>/_data`) but it is only readable as root, and
  letting a host process run as root just to reach it is unacceptable.
- On **macOS / Windows**, the volume lives inside the Docker Desktop VM, so the
  path is not even reachable from the host at all; only Docker Desktop (or a
  container that mounts the volume) can touch the data.

`docker cp` does not help for *live* access: it produces a point-in-time copy,
not a mount, so a host process would never see the agent's new writes.

This document is a proposal for a **volume bridge sidecar**: a small, separate
container that mounts the agent's named volume read-only and exposes it through a
port published only on the host's loopback interface.  A host user can then mount
it at `/some/path` and read the data without root privileges *after the sidecar
has been provisioned*.

That qualification is important.  Creating a container that mounts a named
volume is a trusted Docker-administrator action.  On Linux, access to the Docker
daemon is already enough to start an arbitrary container with that volume mounted
read-write.  This sidecar is consequently not a way to protect the volume from a
Docker administrator; it is a way for that administrator to grant a less-
privileged host reader live, read-only access without giving that reader Docker
or root access.

## Requirements

- **Live read-only access**: the host process can browse current data and cannot
  modify anything in the volume.  This is not a coherent snapshot while the
  agent is writing.
- **No root for the reader**: after a trusted administrator has provisioned the
  sidecar and any platform FUSE/driver prerequisite, the reader can mount and
  use it without root or Docker access.
- **Cross-platform client path**: works on Linux and macOS, and has a documented
  Windows path rather than assuming a Linux kernel client.
- **Consistent with the repo's hardening**: the sidecar itself is unprivileged,
  capability-free, read-only-rootfs, deny-by-default egress, and isolated so the
  agent container cannot reach it.

## Why not NFS?

NFS was the first idea and fails the requirements:

- The host's NFS *client* is in-kernel: `mount -t nfs` requires root, so the
  mount itself is privileged. The same is true of the kernel CIFS (SMB) client.
- A kernel NFS *server* (`nfsd`) inside a container needs `CAP_SYS_ADMIN`
  (effectively privileged). User-space servers (NFS-Ganesha, `unfs3`) avoid that
  but are heavier and still need `CAP_NET_BIND_SERVICE` for port 2049.
- There is no mainstream FUSE-based NFS client, so NFS can never be an
  unprivileged host mount.

The two viable families both use **FUSE on the host side** to make the mount
unprivileged: **SSHFS** and **WebDAV + davfs2**. (A third option exists for
fully Linux hosts: a one-time root `mount --bind` of the volume path — but that
requires host root and is not possible at all when the host is macOS/Windows.)

## Threat model and shared hardening

The sidecar is not the agent container, and is deliberately isolated from it:

- The sidecar runs on its **own Docker network**, not the agent's, so no
  container-IP reachability.
- Its port is published **only** to `127.0.0.1` on the host.  The daemon itself
  must listen on its container interface (`0.0.0.0`), not on the container's own
  loopback address: Docker forwards a published port to the container IP.

This is a deployment constraint, not an absolute statement about every Docker
configuration.  Do not use host networking, do not attach the agent to the
sidecar network, and use a current Docker release: Docker documents caveats for
localhost-published ports on older releases and for direct-routing network
modes.  Verify that an agent container cannot connect to the published service
in the target Docker/Desktop configuration.

The remaining risk is host-side, not agent-side:

- Any local host process can connect to the loopback-published port and attempt
  to exploit the serving daemon (an SFTP server, rclone, …).
- The sidecar necessarily mounts the agent's home volume, which holds
  credentials, tokens, and keys. If the daemon is compromised, those secrets are
  exposed — this is unavoidable, since serving the data requires reading it.

Therefore the sidecar must be hardened exactly like the agent images, so that a
compromised daemon is contained to "can read the volume" and nothing more:

- Run as a non-root user with a configurable `UID`/`GID`.
- `--cap-drop=ALL`; ports are host-published so no capability is needed.
- `--read-only` root filesystem with `/tmp` and `/run` as tmpfs.
- No outbound Internet route.  A plain user-defined bridge does *not* achieve
  this: Docker bridge containers have egress by default.  Create an `--internal`
  network for this one sidecar and do not attach any other containers to it.
  If the threat model also includes host services reachable through Docker's
  bridge gateway, enforce that separately with host firewall policy.
- The agent volume is mounted **read-only** (`-v vol:/vol:ro`) so write access is
  structurally impossible regardless of daemon configuration.
- No host directories are bind-mounted into the sidecar.

## Provisioning boundary

The commands below are performed by a trusted Docker administrator.  They must
also provision the reader's **public** SSH key into the sidecar state.  The
reader generates and retains the corresponding private key locally; a client
private key must never be generated or retained in the sidecar volume.

The administrator creates an internal network once:

```sh
docker network create --internal agent-sidecar-bridge
```

This permits the host-published port while preventing ordinary routed Internet
egress.  It is not a substitute for a host firewall if host-local services are
also out of scope.

## Option A — SSHFS

### How it works

A minimal SFTP server runs in the sidecar, listening on `0.0.0.0:2222` inside
the container and presenting `/vol` as the login account's virtual root. Docker
publishes that port only on host loopback. The host user mounts it with `sshfs`,
a FUSE client that requires no setuid helper and no root after its platform
prerequisites have been installed.

### Sidecar

```sh
docker run -d --name volume-bridge \
  --network agent-sidecar-bridge \
  -p 127.0.0.1:2222:2222 \
  --cap-drop=ALL \
  --read-only \
  --tmpfs /tmp --tmpfs /run \
  -v agent-home-vol:/vol:ro \
  -v volume-bridge-keys:/keys \
  volume-bridge-sftp
```

Key points:

- `agent-home-vol` is the agent's named volume, mounted read-only.
- `volume-bridge-keys` is a small writable volume holding the sidecar's host key
  and its `authorized_keys` state, generated/provisioned on first start.
  Persisting the host key means it does not rotate on restart (a fresh host key
  would break `known_hosts` trust).  It never contains a reader's private key.
- The SFTP server must enforce a **userspace virtual root** at `/vol`, reject
  write operations, and disable shell access, port forwarding, and arbitrary
  command execution.  Its service account must not be able to expose `/keys`.
  Test attempts to traverse above `/vol` and to fetch sidecar configuration.
- Do not implement this with vanilla non-root OpenSSH plus
  `ForceCommand internal-sftp -d /vol -R`: `-d` sets only the initial directory,
  not a filesystem boundary.  OpenSSH's real `ChrootDirectory` needs privileges
  and a root-owned, non-writable chroot path, which are incompatible with the
  stated capability-free sidecar and mutable agent home volume.  Select and
  document an SFTP server that provides the virtual-root restriction without
  those privileges.
- The container runs as a non-root user and the server listens on a high port,
  published by Docker to `127.0.0.1:2222`, so no privileged ports are used.
- The sidecar UID/GID must be able to traverse and read the source home volume.
  Match it to the agent's numeric UID/GID, or explicitly document the narrower
  permission model being served.  Test restrictive paths such as `~/.ssh`.

### Host key distribution (important)

Because the host key is generated on first run, the reader must learn it through
the trusted provisioning path so `sshfs` can verify the sidecar rather than a
local imposter.  The trusted administrator should copy the public host key from
the named state volume via the sidecar and give it to the reader, who pins it in
`known_hosts`.  The same administrator installs the reader's public key as the
sidecar account's `authorized_keys`.

`docker cp` and Docker logs are appropriate only for that trusted administrator;
they are not mechanisms by which an untrusted reader gains access to the Docker
daemon or to the sidecar's state volume.

`ssh-keyscan` remains a fallback only when the resulting fingerprint is compared
with one delivered through that trusted path:

1. **Scan the published loopback port**, then pin the result into the host
   user's `known_hosts`:

   ```sh
   ssh-keyscan -p 2222 -t ed25519 127.0.0.1 >> ~/.ssh/known_hosts
   ```

   By itself this is TOFU: it binds whatever process owns the port at that
   instant.  Compare its fingerprint with the trusted administrator's copy
   before relying on it.

### Host mount

```sh
sshfs -o ro,IdentityFile=~/.ssh/volume_bridge,port=2222 \
  bridge@127.0.0.1:/vol /some/path
```

- `-o ro` plus the server-side read-only enforcement and the `:ro` volume mount
  give three independent layers preventing writes.
- The mount is owned by the host user, so no privilege was involved. If *other*
  host users must read `/some/path`, root makes a one-time edit to
  `/etc/fuse.conf` adding `user_allow_other`, and the mount adds
  `-o allow_other` — an installation-time config, not ongoing root access.
- SSHFS is suitable for live browsing, but it is not a coherence protocol.
  Directory and attribute caches can delay visibility, and a reader can observe
  a file while the agent is still writing it.  Producers should write to a
  temporary name and atomically rename completed files; readers must tolerate
  stale listings and retry as appropriate.

### Trade-offs

- Best live freshness and the most genuinely unprivileged mount (pure FUSE, no
  setuid helper).
- Requires a reader-owned keypair and one-time host-key pinning.
- Works on Linux and macOS via FUSE/macFUSE.  Windows can use WinFsp with
  SSHFS-Win to map an SSHFS drive; this is a separately installed system driver
  and should be tested as part of the Windows support commitment.

## Option B — WebDAV + davfs2

### How it works

A single `rclone serve webdav` process in the sidecar serves the volume's
directory over HTTP, read-only. The host user mounts it with `davfs2`, a FUSE
client.

### Sidecar

```sh
docker run -d --name volume-bridge \
  --network agent-sidecar-bridge \
  -p 127.0.0.1:8080:8080 \
  --cap-drop=ALL \
  --read-only \
  --tmpfs /tmp --tmpfs /run \
  -v agent-home-vol:/vol:ro \
  -v volume-bridge-htpasswd:/etc/rclone \
  volume-bridge-webdav
```

Key points:

- `rclone serve webdav --read-only --addr 0.0.0.0:8080 :local:/vol` serves the
  volume; `--read-only` rejects every write method.  The `0.0.0.0` binding is
  inside the isolated container only; Docker's `-p 127.0.0.1:8080:8080` is what
  restricts host exposure.
- `--htpasswd /etc/rclone/htpasswd` enforces HTTP basic authentication; the
  credentials file lives in a small writable volume so it survives restarts.
- The volume is mounted `:ro` as a second, structural write-prevention layer.
- No SSH anywhere: no keys, no sshd, no known_hosts.

### Host mount

```sh
mount.davfs http://127.0.0.1:8080/ /some/path -o ro
```

- The unprivileged host user mounts via `/usr/sbin/mount.davfs`, which is a
  **setuid-root helper**; the user must be a member of the `davfs2` group.
  Credentials are supplied via `/etc/davfs2/secrets` or per-mount.
- There is no root at *use* time, but the mount path is backed by a setuid-root
  trust anchor on the host — worth weighing against SSHFS's helper-free mount.

### Trade-offs

- No key management; the simplest sidecar of the two.
- `davfs2` buffers and caches, so a read-only mount can lag behind the agent's
  latest writes (stale listings are possible).
- The setuid-root `mount.davfs` helper is a trust anchor and attack surface on
  the host.
- Client is Linux-only; macOS has a built-in WebDAV client, but mounting it
  (`mount_webdav` / Finder) is not a per-user unprivileged FUSE operation.
- rclone's WebDAV server skips symlinks by default, so this option may not show
  every path in a home directory.  That is safer than following links blindly,
  but must be documented to users.

## Recommendation

| Criterion               | SSHFS                          | WebDAV + davfs2                 |
| ----------------------- | ------------------------------ | ------------------------------- |
| Mount without host root | Per-user FUSE after setup      | Via setuid-root `mount.davfs`   |
| Live-ness               | Cached; no snapshot guarantee  | Buffered, can lag               |
| Key management          | Reader key + one-time pin      | HTTP basic auth                 |
| Sidecar complexity      | SFTP server with virtual root  | One `rclone` process            |
| macOS / Windows host    | macFUSE / WinFsp + SSHFS-Win   | Not unprivileged / limited      |
| Write prevention        | `:ro` volume + server read-only| `:ro` volume + `--read-only`    |

Choose **SSHFS** when a per-user mount and cross-platform support matter most.
Choose **WebDAV + davfs2** only when avoiding SSH key management is the priority
and a Linux-only client with a setuid helper and potentially stale reads is
acceptable.  Neither option is a transactional or snapshot view of files that
the agent is actively modifying.

## Security notes

- Never publish the sidecar on anything but `127.0.0.1`; a non-loopback publish
  turns a credentials volume into a network file share.
- Keep the sidecar on its own Docker network so the agent container cannot reach
  it; make that network `--internal` to prevent ordinary Internet egress too.
- The sidecar holds the agent's credentials by necessity; treat its key volume
  and its htpasswd file with the same care as the agent home itself.
- The host key pinning step for SSHFS is not optional ceremony.  `ssh-keyscan`
  alone is TOFU; compare it with a host key received from the trusted
  administrator.
- Test the actual deployment with an agent container on its normal network:
  verify it cannot connect to the published service, verify writes are rejected,
  and verify the intended reader can read a restrictive source home directory.
