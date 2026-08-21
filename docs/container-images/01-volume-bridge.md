---
icon: lucide/folder-key
---

# The `volume-bridge` container

The `volume-bridge` container makes one or more named agent-home volumes available to a
host-side reader over a loopback-only, read-only WebDAV endpoint. macOS and
Windows have built-in WebDAV clients, so this avoids installing a FUSE driver
just to inspect agent state.

Anyone with Docker daemon access on the host can already mount a named volume
directly, read all of it, and, unless careful, write to it too - `volume-bridge`
does not add a boundary that a Docker-privileged actor could not bypass by
mounting the volume themselves. Its value is delegation, not containment:
Docker daemon access is host-root-equivalent, so handing it to a reader or tool
that only needs to inspect one export is usually a far larger privilege grant
than the task requires. `volume-bridge` lets a trusted Docker administrator
publish a narrow, read-only, authenticated slice of a volume to a reader that
must not receive Docker or root access - a native host process, a
non-Docker-aware tool, or a containerized consumer that should not hold a
Docker socket. That reader authenticates with its own revocable WebDAV
credential instead of Docker or OS-level access, and the bridge enforces
read-only independently of how the reader chooses to mount it.

The bridge never mounts a host directory, and agent containers are not
attached to its network. This is useful both for interactive host access and
for host-side tools that need to observe agent state without themselves
becoming a Docker-privileged principal - see [a real use-case: Decant](#a-real-use-case-decant)
below.

## Security model

As described above, this image does not defend a volume against its Docker
administrator; it lets that administrator delegate live read-only access to a
reader that must not receive Docker or root access.

The bridge is designed to run with a read-only root filesystem, no Linux
capabilities, and no host bind mounts. The documented network publishes only
to host loopback; it needs host or network-boundary policy if the bridge itself
also requires deny-by-default egress. Its state volume contains a bcrypt
password verifier only; it must never contain a plaintext reader password,
private key, or unrelated credentials.

Every agent volume is mounted `:ro`, and rclone's WebDAV server is also started
with `--read-only`. The service exposes `/exports` as its virtual root, not the
container filesystem, so its state volume is not reachable through WebDAV.

!!! warning

    The exported homes can contain API tokens, SSH keys, transcripts, and
    source-code fragments. Anyone with the WebDAV credentials can read them.
    Limit each bridge to the volumes and readers that actually need access.

!!! warning

    This image uses HTTP Basic authentication, which does not encrypt the
    password. Publish it only on `127.0.0.1`, use a separate Docker network,
    and never place a LAN-facing reverse proxy in front of it. A
    loopback-only service keeps the credentials off the network; non-loopback
    deployment needs TLS and a separately designed trust setup.

## Build and host prerequisites

Build the image:

```sh
docker build -t volume-bridge:local agent-images/volume-bridge
```

The bridge uses the platform WebDAV client:

- **macOS:** Finder, with no FUSE software required. Choose **Go → Connect to
  Server**, enter `http://127.0.0.1:16080/`, then log in with the bridge username
  and password. Eject the server in Finder when finished.
- **Windows:** Start the built-in **WebClient** service, then use File Explorer's
  **Add a network location** with `http://127.0.0.1:16080/`. Windows refuses
  HTTP Basic authentication by default. Its client must have
  `HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters\BasicAuthLevel`
  set to `2`, then the WebClient service restarted. This is an administrator
  policy change that permits WebClient Basic auth over HTTP generally; make it
  only on a trusted machine and keep this bridge loopback-only.
- **Linux:** install a WebDAV client such as `davfs2`. It commonly uses a
  distribution-provided setuid mount helper, so follow the distribution's
  `davfs2` setup instructions and mount the loopback URL read-only. This is a
  host-client choice; it is not required on macOS or Windows.

On macOS and Windows, use the mounted network location's local path when a
host-side tool needs a filesystem path. Docker Desktop file sharing of that
mount path is platform-specific; verify it before using a containerized
consumer such as Decant.

## Start one bridge

Create a dedicated network and a state volume. The state volume is initialized
with the image's non-root ownership when it is first mounted; do not
pre-populate it using a root-owned helper container.

```sh
docker network create volume-bridge-net
docker volume create volume-bridge-state
```

Choose a strong, unique password. In common POSIX-shell environments, the
following reads it without echoing it. The password is used only to create (or
rotate) the bcrypt verifier in the state volume; it is not written to that
volume. Docker
administrators can inspect a container's environment and are already the
trusted provisioning boundary for the source volumes.

```sh
printf 'WebDAV password: ' >&2
IFS= read -r -s VOLUME_BRIDGE_PASSWORD
printf '\n' >&2
export VOLUME_BRIDGE_PASSWORD
```

The following example exports the Claude Code and Codex home volumes. They are
available below the WebDAV root as `/claude` and `/codex`. The bridge UID/GID
defaults to `1000:1000`; build with `--build-arg UID=… --build-arg GID=…` when
the source volume's owner uses different numeric IDs.

```sh
docker run -d --name volume-bridge \
  --network volume-bridge-net \
  -p 127.0.0.1:16080:16080 \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  --tmpfs /run:rw,noexec,nosuid,nodev \
  --cap-drop=ALL \
  --mount type=volume,src=volume-bridge-state,dst=/state \
  --mount type=volume,src=claude-home,dst=/exports/claude,readonly \
  --mount type=volume,src=codex-home,dst=/exports/codex,readonly \
  -e VOLUME_BRIDGE_USERNAME=bridge \
  -e VOLUME_BRIDGE_PASSWORD \
  volume-bridge:local
unset VOLUME_BRIDGE_PASSWORD
```

This is an ordinary user-defined bridge network, rather than `--internal`, so
Docker Desktop can forward the loopback-published service to the host. It gives
the bridge ordinary Docker-network egress: if deny-by-default egress is required
for the bridge itself, enforce it in the host firewall or network boundary. Keep
the bridge network private: do not attach an agent container to it and do not
use host networking. Docker publishes the WebDAV port only on `127.0.0.1`; the
server listens on `0.0.0.0` *inside* its isolated container because that is
where Docker forwards the published port.

For a single reader with several same-UID volumes, one bridge with multiple
`/exports/<name>` mounts is convenient. That reader can browse every export in
that bridge. Use separate bridges when volumes have different ownership
requirements, readers, lifecycle, or isolation needs.

## Connect and read an export

Authenticate to the base URL, then browse the desired export:

```text
http://127.0.0.1:16080/claude/
http://127.0.0.1:16080/codex/
```

The username defaults to `bridge`; the example explicitly sets it to that
value. A read-only client mount is advisable, but the server's `--read-only`
setting and each source volume's `readonly` mount independently reject writes.
Do not save the password in a project directory or pass it to an agent.

rclone caches directory metadata for one second, but a WebDAV mount is not a
transactional snapshot. Readers can observe a file while an agent is writing it.
Producers should publish completed files by atomic rename where possible, and
consumers should tolerate stale listings and retry.

WebDAV does not represent symlinks. rclone's local backend skips them by
default, which avoids accidentally expanding the export through a link but can
mean that symlinked paths in an agent home are absent from the view.

## Mount exports for a host-side consumer

Mount the individual WebDAV collections at the paths used by the Decant example
below. Each command prompts for the `bridge` credentials; do not put the
password on a command line. Mounting `/claude` and `/codex` separately ensures
the consumer sees only those collections, rather than the bridge's full export
root.

=== "macOS"

    `mount_webdav` uses the built-in WebDAV client and supports an explicit
    mount point, unlike the Finder workflow above:

    ```sh
    mkdir -p "$HOME/agent-sessions/claude" "$HOME/agent-sessions/codex"
    mount_webdav -i -o rdonly http://127.0.0.1:16080/claude/ \
      "$HOME/agent-sessions/claude"
    mount_webdav -i -o rdonly http://127.0.0.1:16080/codex/ \
      "$HOME/agent-sessions/codex"
    ```

    Unmount when finished:

    ```sh
    umount "$HOME/agent-sessions/claude"
    umount "$HOME/agent-sessions/codex"
    ```

=== "Linux"

    Install and configure `davfs2` first. The direct form below uses `sudo` and
    prompts for WebDAV credentials; the `uid` and `gid` options make the mounts
    accessible to the invoking user.

    ```sh
    mkdir -p "$HOME/agent-sessions/claude" "$HOME/agent-sessions/codex"
    sudo mount -t davfs -o ro,uid="$(id -u)",gid="$(id -g)" \
      http://127.0.0.1:16080/claude/ "$HOME/agent-sessions/claude"
    sudo mount -t davfs -o ro,uid="$(id -u)",gid="$(id -g)" \
      http://127.0.0.1:16080/codex/ "$HOME/agent-sessions/codex"
    ```

    Unmount when finished:

    ```sh
    sudo umount "$HOME/agent-sessions/claude"
    sudo umount "$HOME/agent-sessions/codex"
    ```

=== "Windows"

    Map each collection to a drive letter with the built-in WebClient (after
    applying the `BasicAuthLevel` prerequisite above), then create user-owned
    directory junctions for tools that need paths under the user profile:

    ```powershell
    net use V: http://127.0.0.1:16080/claude/
    net use W: http://127.0.0.1:16080/codex/
    New-Item -ItemType Directory -Force "$HOME\agent-sessions" | Out-Null
    cmd /c mklink /J "$HOME\agent-sessions\claude" V:\
    cmd /c mklink /J "$HOME\agent-sessions\codex" W:\
    ```

    Remove the junctions and drive mappings when finished:

    ```powershell
    cmd /c rmdir "$HOME\agent-sessions\claude"
    cmd /c rmdir "$HOME\agent-sessions\codex"
    net use V: /delete
    net use W: /delete
    ```

## A real use-case: Decant

[Decant](https://github.com/dosu-ai/decant) is a local-first analytics tool for
Claude Code and Codex session logs: it indexes transcripts into a local SQLite
archive and serves a web UI with full-text search, token/cost analytics, and
file-hotspot tracking, all without sending data off the host. It can run
natively (via `npx`, an npm global install, or Homebrew) or as a Docker
container; the Docker form mounts the relevant `.claude`/`.codex` directories
from ordinary host paths.

Decant illustrates the delegation this image is for. Whoever launches a
containerized Decant *could* mount `claude-home`/`codex-home` directly - but
only if they already hold Docker daemon access, and a direct volume mount
exposes the entire home directory, not just the session-bearing subdirectories
Decant needs. `volume-bridge` lets the Docker administrator publish read-only,
WebDAV-authenticated access instead: whoever runs Decant needs only a host
filesystem path and the bridge credential, never Docker or root access, and
the final host-side mount step below narrows exposure to `.claude` and
`.codex` specifically.

Mount the relevant session-bearing exports on the host first. Decant expects
the whole `.claude` directory (it resolves `projects` beneath it itself, so do
not point it at `.claude/projects`) and the whole `.codex` directory. Bind the
*host WebDAV paths* mounted above into Decant, not the original named volumes:

```sh
docker run --rm \
  -p 127.0.0.1:3000:3000 \
  -v decant-data:/var/lib/decant \
  -v "$HOME/agent-sessions/claude/.claude:/sources/claude:ro" \
  -v "$HOME/agent-sessions/codex/.codex:/sources/codex:ro" \
  ghcr.io/dosu-ai/decant:latest
```

The preceding commands create the `$HOME/agent-sessions/claude` and
`$HOME/agent-sessions/codex` mount paths. A containerized consumer needs
access to those paths through Docker Desktop's sharing mechanism.

!!! note "Alternatives evaluated and not recommended"

    Two other ways of getting this data into Decant were tried and rejected.
    Mounting `claude-home`/`codex-home` directly into a Decant container,
    narrowed with `--mount ...,volume-subpath=.claude` (Docker Engine 25+)
    instead of using `volume-bridge`, needs Docker daemon access - already
    host-root-equivalent - just to read session logs, and failed Decant's sync
    outright in testing. Running Decant natively (`npx @dosu/decant@latest
    serve --claude-dir ... --codex-dir ...`) against the same WebDAV mounts
    avoids Docker entirely, but on Linux took an impractically long time to
    sync and load the web UI. The containerized option above was the only one
    that worked well.

## Password rotation and troubleshooting

- To rotate the password, restart with both `VOLUME_BRIDGE_USERNAME` and
  `VOLUME_BRIDGE_PASSWORD` set. This replaces the state volume's bcrypt verifier.
  The bootstrap interface deliberately supports one reader account; use separate
  bridges for distinct readers or manage a multi-user `htpasswd` file through a
  trusted Docker-administration process.
- Keep `volume-bridge-state`. Deleting it removes the password verifier and
  makes `VOLUME_BRIDGE_PASSWORD` mandatory on the next start.
- If startup says `/state` is not writable, use a newly created state volume or
  initialize its ownership through the trusted Docker administration process.
- If source paths are unreadable, rebuild the image with the agent volume's
  numeric UID/GID. Do not solve this by adding `DAC_OVERRIDE`.
- If Windows does not show a credentials prompt, check that WebClient is running
  and that its `BasicAuthLevel` policy permits loopback HTTP Basic auth.
- Verify the security properties in the target Docker/Desktop environment:
  agents cannot connect to the bridge, write attempts are rejected, and only the
  intended reader can authenticate.
