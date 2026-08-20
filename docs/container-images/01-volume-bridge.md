---
icon: lucide/folder-key
---

# The `volume-bridge` container

`volume-bridge` makes one or more named agent-home volumes available to a
host-side reader over a loopback-only, read-only SFTP endpoint. The reader
mounts individual exports with SSHFS; the bridge never mounts a host directory
and never receives the reader's private key.

This is useful both for interactive host access and for host-side tools that
need to observe agent state. For example, [Decant](https://github.com/dosu-ai/decant)
indexes Claude Code and Codex session logs from ordinary paths on the host. A
host SSHFS mount lets Decant consume those logs while the agents retain their
named-volume homes and do not receive access to Decant.

## Security model

The Docker operator who creates a container with a named volume is trusted: on
Linux, Docker-daemon access already permits creating another container with that
volume mounted read-write. This image does not defend a volume against its
Docker administrator. Instead, it lets that administrator grant a host reader
live read-only access without granting the reader Docker or root access.

The bridge is designed to run with a read-only root filesystem, no Linux
capabilities, no host bind mounts, and no routed Internet egress. Its state
volume contains only the bridge's SSH host key and authorized public keys. It
must never contain a reader private key.

Every agent volume is mounted `:ro`, and rclone's SFTP server is also started
with `--read-only`. The service exposes `/exports` as its virtual root, not the
container filesystem, so its state volume is not reachable through SFTP.

!!! warning

    The exported homes can contain API tokens, SSH keys, transcripts, and
    source-code fragments. Anyone holding an authorized reader key can read
    them. Limit each bridge to the volumes and readers that actually need
    access.

## Build and host prerequisites

Build the image:

```sh
docker build -t volume-bridge:local agent-images/volume-bridge
```

Install an SSHFS client on the machine that will mount the export:

- Linux: `fuse3` and `sshfs`.
- macOS: macFUSE and `sshfs`.
- Windows: WinFsp and SSHFS-Win.

The FUSE/driver installation can need administrator approval. Once installed,
the reader can mount with their own account and does not need root or Docker
access. Windows users can map a drive with SSHFS-Win; Decant currently ships
native binaries for macOS and Linux, not Windows.

Generate a reader keypair on the host and keep its private half there:

```sh
ssh-keygen -t ed25519 -f "$HOME/.ssh/volume-bridge" -C volume-bridge-reader
```

## Start one bridge

Create an internal network and a state volume. The state volume is initialized
with the image's non-root ownership when it is first mounted; do not pre-populate
it using a root-owned helper container.

```sh
docker network create --internal volume-bridge-net
docker volume create volume-bridge-state
```

The following example exports the Claude Code and Codex home volumes. They are
available to the SFTP client as `/claude` and `/codex`, respectively. The bridge
UID/GID defaults to `1000:1000`; build with `--build-arg UID=… --build-arg GID=…`
when the source volume's owner uses different numeric IDs.

```sh
docker run -d --name volume-bridge \
  --network volume-bridge-net \
  -p 127.0.0.1:2222:2222 \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  --tmpfs /run:rw,noexec,nosuid,nodev \
  --cap-drop=ALL \
  --mount type=volume,src=volume-bridge-state,dst=/state \
  --mount type=volume,src=claude-home,dst=/exports/claude,readonly \
  --mount type=volume,src=codex-home,dst=/exports/codex,readonly \
  -e VOLUME_BRIDGE_AUTHORIZED_KEY="$(cat "$HOME/.ssh/volume-bridge.pub")" \
  volume-bridge:local
```

`--internal` removes normal routed Internet egress. It does not replace host
firewall policy for services reachable through Docker's bridge gateway. Keep the
bridge network private: do not attach an agent container to it and do not use
host networking. Docker publishes the SFTP port only on `127.0.0.1`; the server
listens on `0.0.0.0` *inside* its isolated container because that is where Docker
forwards the published port.

For a single reader with several same-UID volumes, one bridge with multiple
`/exports/<name>` mounts is convenient. Use separate bridges when volumes have
different ownership requirements, readers, lifecycle, or isolation needs.

## Pin the host key and mount an export

Copy the bridge public host key through the trusted Docker-administrator path,
then create a dedicated known-hosts file for the reader:

```sh
docker cp volume-bridge:/state/ssh_host_ed25519_key.pub "$HOME/.ssh/volume-bridge-host.pub"
awk '{print "[127.0.0.1]:2222 " $1 " " $2}' \
  "$HOME/.ssh/volume-bridge-host.pub" > "$HOME/.ssh/known_hosts.volume-bridge"
chmod 600 "$HOME/.ssh/known_hosts.volume-bridge"
```

Mount just the desired export. The remote `/claude` path is relative to the
bridge's virtual root, so it cannot reach `/state` or the container root:

```sh
mkdir -p "$HOME/agent-sessions/claude"
sshfs -o ro,port=2222,IdentityFile="$HOME/.ssh/volume-bridge",\
UserKnownHostsFile="$HOME/.ssh/known_hosts.volume-bridge",\
StrictHostKeyChecking=yes \
  bridge@127.0.0.1:/claude "$HOME/agent-sessions/claude"
```

Unmount with `fusermount3 -u` on Linux, `umount` on macOS, or the SSHFS-Win
drive-unmount workflow on Windows.

SSHFS and rclone both cache directory metadata; the bridge sets rclone's cache
to one second, but a mount is not a transactional snapshot. Readers can observe
a file while an agent is writing it. Producers should publish completed files by
atomic rename where possible, and consumers should tolerate stale listings and
retry.

## Decant example

Mount the relevant session-bearing exports on the host first. Claude Code stores
project transcripts under `.claude/projects`; Decant's documented Docker example
also reads the Codex home directory. Bind those *host SSHFS paths* into Decant,
not the original named volumes:

```sh
mkdir -p "$HOME/agent-sessions/codex"
sshfs -o ro,port=2222,IdentityFile="$HOME/.ssh/volume-bridge",\
UserKnownHostsFile="$HOME/.ssh/known_hosts.volume-bridge",\
StrictHostKeyChecking=yes \
  bridge@127.0.0.1:/codex "$HOME/agent-sessions/codex"

docker run --rm \
  -p 127.0.0.1:3000:3000 \
  -v decant-data:/var/lib/decant \
  -v "$HOME/agent-sessions/claude/.claude/projects:/sources/claude:ro" \
  -v "$HOME/agent-sessions/codex:/sources/codex:ro" \
  ghcr.io/dosu-ai/decant:latest
```

On Linux, a containerized consumer may need the SSHFS mount created with
`allow_other` and the host's `/etc/fuse.conf` configured with `user_allow_other`.
That is a host-wide administrator decision: it lets processes other than the
mounting user access the mount. Prefer running a consumer as the mounting user
when possible, and test Docker Desktop file-sharing behavior separately on
macOS and Windows.

## Key rotation and troubleshooting

- To authorize a new reader key, restart with
  `VOLUME_BRIDGE_AUTHORIZED_KEY` set to the replacement public key. The image
  bootstrap interface deliberately accepts one key. Use separate bridges for
  distinct readers or manage a multi-key `authorized_keys` file through a
  trusted administration process.
- Keep `volume-bridge-state`. Deleting it rotates the host key and invalidates
  the pinned known-hosts entry.
- If startup says `/state` is not writable, use a newly created state volume or
  initialize its ownership through the trusted Docker administration process.
- If source paths are unreadable, rebuild the image with the agent volume's
  numeric UID/GID. Do not solve this by adding `DAC_OVERRIDE`.
- Verify the security properties in the target Docker/Desktop environment:
  agents cannot connect to the bridge, writes through SFTP are rejected, and
  only the intended reader key can authenticate.
