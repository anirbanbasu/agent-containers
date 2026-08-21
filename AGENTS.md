# AGENTS.md

## Project purpose

This repository builds hardened Docker images for command-line coding agents.
The containment guarantees are central to the project: unprivileged execution,
a read-only root filesystem, minimal capabilities, and deny-by-default egress.
Read [the containment philosophy](docs/containment-philosophy.md) before
changing image hardening or networking behaviour.

## Working conventions

- Preserve unrelated working-tree changes. Do not reset, discard, or reformat
  files outside the requested scope.
- Keep credentials, tokens, and private keys out of images, build arguments,
  committed files, and command output. Authentication state belongs in a
  mounted persistent home volume.
- Use `apply_patch` for repository edits. Prefer `rg` for searching.
- Add or update documentation alongside image or runtime changes. The relevant
  image page lives in `docs/container-images/`.
- Explain any change that weakens containment or expands default network
  access. New default egress hosts must be necessary and documented.

## Image conventions

Workload images in `agent-images/<name>/` normally:

- use a non-root user with configurable `UID` and `GID`;
- are designed to run with `--read-only`, `/tmp` and `/run` tmpfs mounts, and
  `--cap-drop=ALL`;
- use the shared `egress-allowlist.sh` and support the `AGENT_*` gateway
  contract;
- provide a persistent home volume and a `/workspace` work directory;
- install optional user-selected tools through `packages-apt.txt`,
  `packages-npm.txt`, and `packages-uv.txt` rather than editing the required
  infrastructure package list.

Use `claude-code` as the template for a first-party CLI image and `hermes`
when evaluating an image built on an upstream vendor base image. Do not seed
credentials, plugins, or skills unless the requested image explicitly calls
for them.

`volume-bridge` is not a workload image and is deliberately exempt from the
shared `egress-allowlist.sh` convention: it has no legitimate outbound need at
all (it only serves inbound WebDAV reads from a local backend), so it hard-codes
a small, non-configurable deny-by-default `iptables`/`ip6tables` policy for
both `INPUT` (only its WebDAV port, plus loopback/established) and `OUTPUT`
(loopback/established only) instead of pulling in the allowlist script's
`AGENT_ALLOWED_EGRESS`/`ipset`/`dnsmasq` machinery, which exists only to open
exceptions this image should never have. Treat other pure-infrastructure
images the same way if they have no legitimate outbound need: prefer a fixed
deny-all over a configurable allowlist that could be misconfigured open.

## Required integration work

When adding or removing an `agent-images/<name>/` directory:

1. Add or update its page in `docs/container-images/` and the image index.
2. Update `README.md` and `SECURITY.md` when the image is user-facing.
3. Run `just update-issue-templates` to regenerate component choices.
4. Update cross-image documentation where its statements are no longer true.

## Verification

Run the checks proportionate to the change:

```sh
bash -n agent-images/<name>/entrypoint.sh
docker build --build-context shared=agent-images/shared \
  -t <name>:local agent-images/<name>
just check-issue-templates
zensical build --clean
git diff --check
```

For a new or changed image, also smoke-test the installed CLI and unprivileged
execution using the documented security flags and a mounted persistent home
volume. Do not attempt real account logins or expose secrets during tests.
