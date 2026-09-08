---
icon: lucide/folder-key
---

# The `volume-bridge` container

The `volume-bridge` container makes one or more named agent-home volumes available to a
host-side reader over a loopback-only, read-only WebDAV endpoint. macOS and
Windows have built-in WebDAV clients, so this avoids installing a FUSE driver
just to inspect agent state.

Anyone with Docker daemon access on the host can already mount a named volume
directly, read all of it, and, unless careful, write to it too — `volume-bridge`
does not add a boundary that a Docker-privileged actor could not bypass by
mounting the volume themselves. Its value is delegation, not containment:
Docker daemon access is host-root-equivalent, so handing it to a reader or tool
that only needs to inspect one export is usually a far larger privilege grant
than the task requires. `volume-bridge` lets a trusted Docker administrator
publish a narrow, read-only, authenticated slice of a volume to a reader that
must not receive Docker or root access — a native host process, a
non-Docker-aware tool, or a containerized consumer that should not hold a
Docker socket. That reader authenticates with its own revocable WebDAV
credential instead of Docker or OS-level access, and the bridge enforces
read-only independently of how the reader chooses to mount it.

The bridge never mounts a host directory, and agent containers are not
attached to its network. This is useful both for interactive host access and
for host-side tools that need to observe agent state without themselves
becoming a Docker-privileged principal — see [a real use-case: Decant](#a-real-use-case-decant)
below.

## Security model

As described above, this image does not defend a volume against its Docker
administrator; it lets that administrator delegate live read-only access to a
reader that must not receive Docker or root access.

The bridge is designed to run with a read-only root filesystem and no host
bind mounts. It never needs outbound network access at all — it only serves
inbound WebDAV reads from a local `/exports` backend — so instead of the
shared, configurable `egress-allowlist.sh` used by the CLI agent images (see
[the containment philosophy](../containment-philosophy.md)), its entrypoint
installs a small, fixed, non-configurable `iptables`/`ip6tables` policy: deny
all `OUTPUT` except loopback and established/related traffic, and deny all
`INPUT` except loopback, established/related, and new connections to the
WebDAV port. That is a stricter guarantee than a default-deny allowlist,
since there is no `AGENT_ALLOWED_EGRESS`-style variable that could ever
loosen it. Installing those rules needs `NET_ADMIN` and `NET_RAW`; the
entrypoint then uses `gosu` (needing `SETUID`/`SETGID`) to drop from root to
the unprivileged bridge user before `rclone` ever runs. Its state volume
contains a bcrypt password verifier only; it must never contain a plaintext
reader password, private key, or unrelated credentials.

Every agent volume is mounted `:ro`, and rclone's WebDAV server is also started
with `--read-only`. The service exposes `/exports` as its virtual root, not the
container filesystem, so its state volume is not reachable through WebDAV.
Rejected writes come back as a `404`, not the more idiomatic `403`/`405` — an
inconsistent status code, not a gap in the read-only enforcement itself.

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

!!! warning

    "Loopback-only" binds to `127.0.0.1` on whatever machine the Docker
    *daemon* runs on, not necessarily the machine you're typing on. On a
    remote or shared daemon — an SSH-forwarded `DOCKER_HOST`, a cloud dev box,
    some Colima/Lima setups — `127.0.0.1` means "reachable by any other local
    user on that host." This image assumes a single-user local daemon; on a
    shared one, treat the bridge as reachable by every other local account.
    `rclone`'s WebDAV server has no brute-force lockout or rate limiting on
    Basic Auth, so that assumption matters: a loopback bind alone does not
    stop another local user on a shared host from guessing the password.

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

Choose a strong, unique password. The password is used only to create (or
rotate) the bcrypt verifier in the state volume; it is not written to that
volume.

Prefer `VOLUME_BRIDGE_PASSWORD_FILE` over `VOLUME_BRIDGE_PASSWORD` where the
password can be delivered as a bind-mounted file: `-e VOLUME_BRIDGE_PASSWORD`
sends the resolved value to the Docker daemon, which stores it in that
container's config for as long as the container exists — readable by anyone
who can `docker inspect` it, not just at launch. `VOLUME_BRIDGE_PASSWORD_FILE`
is read once at startup and never lands in that persisted config. Docker
administrators can already read the source volumes directly either way, so
this isn't about a more-privileged actor — it's about not leaving the
plaintext in a place that support bundles, `docker inspect` dumps, or CI logs
routinely capture.

```sh
umask 077
printf 'WebDAV password: ' >&2
IFS= read -r -s webdav_password
printf '\n' >&2
printf '%s' "$webdav_password" > /tmp/volume-bridge-password
unset webdav_password
```

The following example exports the Claude Code and Codex home volumes. They are
available below the WebDAV root as `/claude` and `/codex`. The bridge UID/GID
defaults to `1000:1000`; build with `--build-arg UID=… --build-arg GID=…` when
the source volume's owner uses different numeric IDs. Workload images such as
`claude-code` are normally themselves built with
`--build-arg UID=$(id -u) --build-arg GID=$(id -g)`, remapping their account to
the operator's host UID/GID rather than the placeholder `1000:1000` (see that
image's Dockerfile) — so build `volume-bridge` the same way,
`--build-arg UID=$(id -u) --build-arg GID=$(id -g)`, unless you know the
source volume was built with different, fixed IDs. A mismatch here does not
always fail loudly; see
[Password rotation and troubleshooting](#password-rotation-and-troubleshooting).

```sh
docker run -d --name volume-bridge \
  --network volume-bridge-net \
  -p 127.0.0.1:16080:16080 \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  --tmpfs /run:rw,noexec,nosuid,nodev \
  --cap-drop=ALL \
  --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  --mount type=volume,src=volume-bridge-state,dst=/state \
  --mount type=volume,src=claude-home,dst=/exports/claude,readonly \
  --mount type=volume,src=codex-home,dst=/exports/codex,readonly \
  --mount type=bind,src=/tmp/volume-bridge-password,dst=/run/secrets/volume-bridge-password,readonly \
  -e VOLUME_BRIDGE_USERNAME=bridge \
  -e VOLUME_BRIDGE_PASSWORD_FILE=/run/secrets/volume-bridge-password \
  volume-bridge:local
rm -f /tmp/volume-bridge-password
```

| Capability | Why it's needed |
| --- | --- |
| `NET_ADMIN`, `NET_RAW` | The entrypoint always installs its fixed deny-by-default `iptables`/`ip6tables` policy (see [Security model](#security-model)), even though there is no allowlist to configure. |
| `SETUID`, `SETGID` | Needed for `gosu` to drop from root to the unprivileged `bridge` user once that policy is installed. |

This is an ordinary user-defined bridge network, rather than `--internal`, so
Docker Desktop can forward the loopback-published service to the host. Keep
the bridge network private: do not attach an agent container to it and do not
use host networking. Docker publishes the WebDAV port only on `127.0.0.1`; the
server listens on `0.0.0.0` *inside* its isolated container because that is
where Docker forwards the published port. The container's own network policy
denies it all other inbound and outbound traffic regardless of what the
Docker network otherwise permits.

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

Prefer a native OS WebDAV client mount (below) over authenticating in a
general-purpose browser tab. A browser that has ever authenticated to the
bridge's origin auto-attaches the cached credential to later requests from any
page it visits, including third-party ones — a low-likelihood but avoidable
exposure. Reads are blocked cross-origin by CORS and writes are already
rejected server-side, so the practical risk is small, but closing the browser
tab (or logging out) after use avoids it entirely.

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

Which setup applies depends on who runs Decant:

- **The Decant operator already has Docker daemon access** — the common case
  for a local, single-user tool: mount `claude-home`/`codex-home` directly,
  narrowed to the session-bearing subdirectory with
  `--mount ...,volume-subpath=.claude` (Docker Engine 25+). No `volume-bridge`
  needed.
- **The Decant operator must not receive Docker or root access** — a
  teammate, a non-Docker-aware host tool, or any consumer kept out of the
  Docker group: publish read-only, WebDAV-authenticated access through
  `volume-bridge` instead, and mount the resulting host WebDAV paths into
  Decant.

### Direct mount (Decant operator has Docker access)

Decant's own Dockerfile does not hard-code its `999:999` user: it just runs
`useradd --system`, and `999` is where that lands on top of a fresh
`debian:bookworm-slim` layer (Debian's default system-UID range in
`/etc/login.defs` is `100`–`999`, and `decant` is the first system account
the image creates). That UID/GID generally won't match `claude-home`/
`codex-home` (commonly the invoking host user's own UID/GID, e.g.
`1000:1000`). Fix that at the source with a small downstream image that
renumbers Decant's `decant` account, at container start, to whatever UID/GID
actually owns the mounted volumes, rather than loosening permissions on the
volumes themselves. Its `/var/lib/decant` SQLite state is re-owned to the
same account on every start, so — unlike overriding `--user` directly against
the upstream image — Decant's database stays writable by whichever account
ends up running it (`unable to open database file` otherwise).

This avoids a `chmod -R o+rX` on the source volumes entirely. `chmod` is a
one-time snapshot: it does not cover directories an agent creates *after* it
runs, such as a new `~/.claude/sessions` entry on a later Claude Code
startup, so the mismatch silently comes back as new files accumulate. A
derived image that instead makes Decant run *as* the volume's actual owning
UID reads those new paths correctly the moment they appear, with nothing to
re-run.

Save the following as `Dockerfile` and `entrypoint.sh` in an empty directory:

This Decant launch does not carry the workload hardening flags: its entrypoint
must start as root to renumber the `decant` account, it runs no model, and both
source mounts are read-only.

```dockerfile
FROM ghcr.io/dosu-ai/decant:latest@sha256:7f3653ca8d6be7d06c8b1933d2547869588a63bfa95e966e8a0145cc25234bec

USER root
COPY entrypoint.sh /usr/local/bin/decant-entrypoint.sh
RUN chmod +x /usr/local/bin/decant-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/decant-entrypoint.sh"]
CMD ["serve", "--host", "0.0.0.0", "--port", "3000", "--no-fs-watch", "--interval-ms", "45000"]
```

```sh
#!/bin/sh
set -eu

if [ -n "${DECANT_UID:-}" ] && [ -n "${DECANT_GID:-}" ]; then
  uid="$DECANT_UID"
  gid="$DECANT_GID"
elif [ -d /sources/claude ]; then
  uid=$(stat -c '%u' /sources/claude)
  gid=$(stat -c '%g' /sources/claude)
elif [ -d /sources/codex ]; then
  uid=$(stat -c '%u' /sources/codex)
  gid=$(stat -c '%g' /sources/codex)
else
  echo "entrypoint: no /sources/claude or /sources/codex mounted, and no DECANT_UID/DECANT_GID set" >&2
  exit 1
fi

current_uid=$(id -u decant)
current_gid=$(id -g decant)

if [ "$uid" != "$current_uid" ] || [ "$gid" != "$current_gid" ]; then
  groupmod -g "$gid" decant
  usermod -u "$uid" -g "$gid" decant
fi

chown -R decant:decant /var/lib/decant

exec setpriv --reuid decant --regid decant --init-groups /usr/local/bin/decant "$@"
```

The entrypoint runs as root only long enough to renumber the `decant` account
and re-own its state directory, then uses `setpriv` — already present in the
upstream `debian:bookworm-slim` base, so nothing extra to install — to `exec`
into the real `decant` binary as that account. That's a true process
replacement, not a forked wrapper, so PID 1 still receives and handles
signals normally. No `--build-arg` is needed: the UID/GID are read from
whichever volumes are mounted at `/sources/claude` or `/sources/codex` when
the container starts, so the same built image works for any operator without
a rebuild. Set `DECANT_UID`/`DECANT_GID` explicitly to skip auto-detection.

```sh
docker build -t decant-matched:local .
```

```sh
docker run -d \
  -p 127.0.0.1:3000:3000 \
  -v decant-data:/var/lib/decant \
  --mount type=volume,source=claude-home,target=/sources/claude,readonly,volume-subpath=.claude \
  --mount type=volume,source=codex-home,target=/sources/codex,readonly,volume-subpath=.codex \
  decant-matched:local
```

This is also the option that has tested best: Decant's sync and in-UI update
both work reliably against the named volumes directly, which was not
consistently true of the WebDAV-mounted host paths below.

!!! note "If `claude-home` and `codex-home` have different owners"

    The entrypoint above assumes both volumes share one UID/GID pair — the
    common case for a single operator's own agent homes. `decant` is one
    account, so it can only be renumbered to match one owner; if the two
    volumes are genuinely owned by different UID/GID pairs, renumbering to
    match one of them still leaves the other unreadable. Prefer a POSIX
    *default* ACL over a `chmod -R o+rX` on the mismatched volume, granting
    read access to the UID `decant` was renumbered to (i.e. the *other*
    volume's owner — `claude-home`'s UID/GID in this example, if
    `codex-home` is the mismatched one):

    ```sh
    docker run --rm -v codex-home:/vol debian:bookworm-slim \
      sh -c 'apt-get update -qq && apt-get install -qq -y acl >/dev/null &&
             setfacl -R -d -m u:<claude-home-uid>:rX -m u:<claude-home-uid>:rX /vol'
    ```

    Unlike `chmod`, a default ACL is inherited by files and directories
    created after it is set, so it does not silently stop covering new
    session directories the way a one-time `chmod` does. This needs the `acl`
    package and a volume backend that supports POSIX ACLs (true for ordinary
    ext4/xfs; confirm this holds under Docker Desktop's VM before relying on
    it there). Running two separate Decant containers, one per volume, is the
    alternative, but was ruled out: Decant correlates Claude and Codex data
    together, so splitting them into separate instances defeats the point.

### Delegated mount via `volume-bridge` (Decant operator has no Docker access)

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
  ghcr.io/dosu-ai/decant:latest@sha256:7f3653ca8d6be7d06c8b1933d2547869588a63bfa95e966e8a0145cc25234bec
```

The preceding commands create the `$HOME/agent-sessions/claude` and
`$HOME/agent-sessions/codex` mount paths. A containerized consumer needs
access to those paths through Docker Desktop's sharing mechanism.

!!! note "Earlier testing notes"

    Mounting `claude-home`/`codex-home` directly, narrowed with
    `--mount ...,volume-subpath=.claude`, first failed Decant's sync outright.
    That turned out to be a UID mismatch between Decant's fixed `999:999` user
    and the volumes' `1000:1000` ownership, not a limitation of
    `volume-subpath` mounts themselves — the downstream image above resolves
    it by renumbering Decant's account instead, which is why the direct-mount
    option is now recommended when the operator already has Docker access.
    An earlier revision of this doc used a one-time `chmod -R o+rX` on the
    source volumes instead; that worked for existing files but silently
    stopped covering directories created after the `chmod` ran (e.g. a new
    `~/.claude/sessions` entry on a later Claude Code startup), so it was
    replaced with the account-renumbering approach above.

    Running Decant natively (`npx @dosu/decant@latest serve --claude-dir ...
    --codex-dir ...`) against the WebDAV-mounted host paths avoids Docker
    entirely, but on Linux took an impractically long time to sync and load
    the web UI.

## Password rotation and troubleshooting

- To rotate the password, restart with `VOLUME_BRIDGE_USERNAME` and either
  `VOLUME_BRIDGE_PASSWORD` or `VOLUME_BRIDGE_PASSWORD_FILE` set. This replaces
  the state volume's bcrypt verifier. The bootstrap interface deliberately
  supports one reader account; use separate bridges for distinct readers or
  manage a multi-user `htpasswd` file through a trusted Docker-administration
  process.
- Keep `volume-bridge-state`. Deleting it removes the password verifier and
  makes `VOLUME_BRIDGE_PASSWORD`/`VOLUME_BRIDGE_PASSWORD_FILE` mandatory on the
  next start.
- If startup says `/state` is not writable, use a newly created state volume or
  initialize its ownership through the trusted Docker administration process.
- If source paths are unreadable, rebuild the image with the agent volume's
  numeric UID/GID. Do not solve this by adding `DAC_OVERRIDE`.
- A UID/GID mismatch does not always surface as a permission error: it can
  instead mount successfully but show an empty (or partially empty) directory
  on the client, with nothing wrong-looking in the container logs. rclone's
  WebDAV server is built on Go's `golang.org/x/net/webdav`, which has a
  long-standing bug where hitting a permission-denied file partway through
  building a directory's PROPFIND response emits a truncated response instead
  of a clean error ([golang/go#43782](https://github.com/golang/go/issues/43782)) —
  `davfs2`'s `neon`-based client then renders that as an empty listing rather
  than a mount failure. If a mount looks empty despite a non-empty source
  volume, check ownership before assuming a client-side problem:
  ```sh
  docker run --rm -v <source-volume>:/data:ro debian:trixie-slim \
    find /data -not -user <bridge-uid> -o -not -group <bridge-gid>
  ```
  Any output identifies files the bridge user can't read. A raw `curl -u
  bridge -X PROPFIND -H "Depth: 1" http://127.0.0.1:16080/<export>/` bypasses
  the client entirely and helps confirm whether the response looks truncated
  before rebuilding the image with matching `UID`/`GID` build args.
- If Windows does not show a credentials prompt, check that WebClient is running
  and that its `BasicAuthLevel` policy permits loopback HTTP Basic auth.
- Verify the security properties in the target Docker/Desktop environment:
  agents cannot connect to the bridge, write attempts are rejected, and only the
  intended reader can authenticate.
