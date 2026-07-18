---
icon: lucide/volleyball
---

# The containment philosophy

By now, you have probably come to appreciate why containers for coding agents are a good idea. But to what lengths do we need to go to ensure proper containment? Why not just run the agent in a (Docker) container and call it a day?

In this section, we will explore the philosophy behind the containment strategy used in this project, and why it is necessary to go beyond just running the agent in a container.

!!! info "The containment philosophy"
    
    Don't ask the thing inside the sandbox to behave — put the walls where it can't reach them.

## Filesystem containment

The root filesystem of the container is mounted read-only. That's not a suggestion enforced by convention — it's the kernel refusing every attempt to touch it, agent-directed or not. `apt install whatever`, editing a system binary, quietly patching a script under `/usr` — all of it fails the same way, whether the request came from a coding agent following an injected instruction or from you, connected to `/bin/bash` inside the running container as `root`. Root, in this context, isn't a magic word; it's just a UID with nothing left to write to.

The only part of the host that crosses into the container at all is the one project directory chosen for the task, bind-mounted explicitly at container start. Everything else on the host — other projects, your home directory, your credentials — has no path in. It isn't hidden or permission-denied; it simply was never mounted, so as far as the agent's filesystem view is concerned, it doesn't exist. Ephemeral scratch space (`/tmp`, `/run`) is backed by `tmpfs`, so anything dropped there vanishes the moment the container exits — no cruft quietly accumulating between unrelated tasks.

None of this makes the container useless for real work, though — a coding agent that can't install a package isn't a coding agent, it's a paperweight. The trick is scoping the exception, not removing the rule: a project's own package installs (a `.venv`, a `node_modules`) land inside the bind-mounted project directory itself, isolated by nothing more than being separate directories, and persist or disappear exactly as the project does. Anything that needs to live outside a single project — global tool installs, package caches — has exactly one other writable home: a named volume mounted at `/home/agent-user`, the home directory of the unprivileged `agent-user` the agent runs as. That volume is genuinely shared and persists across container runs, so it isn't isolation in the same sense as the project mount — two global installs of the same tool at different versions can still collide there, same as on a bare host. What keeps that manageable differs by ecosystem: a content-addressed package cache, keyed by exact version, can be shared freely with no conflict at all, while a genuinely global install is shared mutable state like any other, and a project with unusual version needs is better off reaching for its own project-scoped install than the global one.

!!! info "Principle"

    Read-only by default, write access only where it is explicitly specified.

## Process containment

Everything the agent actually does — reading files, running a build, invoking tools — happens as an unprivileged, non-root user, created with a UID matched to the host's so bind-mounted files don't end up owned by a stranger. Root does exist fleetingly, at container start, but only to do the one thing an unprivileged process structurally cannot: set up the firewall rules described below. The moment that's done, the startup process hands off and drops to the unprivileged user for the rest of the container's life — the agent itself never holds root.

Linux capabilities are stripped down to the bare minimum this setup requires (principally the ability to configure networking, and only because the firewall has to be installed from inside the container's own network namespace). Nothing about running a coding agent needs the ability to bind privileged ports, load kernel modules, or override file ownership checks — so those capabilities simply aren't there to misuse, whether by design or by accident.

!!! info "Principle"

    No root, no more privilege than the job requires.

## Network containment

No outbound connection succeeds unless something has explicitly said it may. A dedicated resolver answers DNS only for hostnames on the allowlist and records their resolved addresses as they're looked up; firewall rules then permit outbound traffic only to addresses on that record, and drop everything else. Nothing is allowed by omission — an unconfigured container defaults to deny-all, not open access, and says so loudly rather than failing silently.

For a stronger guarantee than _the container promises to enforce its own rules_, that same allowlist logic can be lifted out of the workload container entirely and placed on a dedicated gateway — a second, purpose-built container that owns the firewall rules the workload is subject to, whether it happens to sit right next to the workload on the same host or on a separate machine you control elsewhere. The workload tunnels all outbound traffic to it and treats everything else as unreachable; reachability is the only thing that changes between "gateway next door" and "gateway on the other side of the world," not the guarantee itself. Putting the gateway on a genuinely separate machine adds one further property on top: even a full compromise of the machine running the agent gives an attacker no path to the rules governing what it's allowed to talk to, since those rules never lived on that machine to begin with.

Worth being explicit about: the specific mechanism this project ships for that tunnel — SSH (via `sshuttle`), with an optional Cloudflare Tunnel for a gateway with no inbound port open at all — is a reference implementation and a quick start, not the only correct way to satisfy the underlying rule. The contract is just that the workload has no route out except through a boundary it doesn't control the rules of. A system administrator with an existing trusted network already in place — an organisational VPN, a WireGuard mesh, a Cisco AnyConnect endpoint — can swap that client in for `sshuttle` and point the same workload container at infrastructure they already run, with no change to filesystem or process containment at all.

!!! info "Principle"

    Denied by default, exceptions managed explicitly.

## Known limitations

No boundary described above is a promise that nothing can go wrong — it's a bound on how far things go when something does. A few gaps are worth naming plainly, so trust in this design rests on what it actually does rather than what it sounds like it does.

- **The project mount is a two-way door.** The one directory the agent can write to is also the one directory that survives the container — code, config, and hooks written there maybe read and executed on the host once the container exits, e.g., a `postinstall` script in `package.json`, a `Makefile` target, a `.git/hooks` entry, a CI workflow file that a real runner will execute with its own credentials, an IDE task or launch config, a `.envrc` picked up by direnv. Filesystem containment stops the agent reaching out to the host while it's running; it does nothing to vet what the agent leaves behind for any process on the host to run later. A malicious or careless edit here is a plan for the *next* thing that executes on the host, not for the container.
- **Any credential handed to the agent is a bridge, not a breach.** A git remote with push access, an API token in an environment variable, a package registry auth file — none of these need an "escape" to be abused, because they were legitimately granted and their destination is, almost by definition, on the network allowlist (cloning or pushing wouldn't work otherwise). Egress control governs *where* traffic can go, not *what* it's allowed to do once it gets there.
- **The allowlist is host-based, not content-based.** Permitting the default package registries or a code-hosting domain is close to unavoidable for real work, and both are also the easiest imaginable vector for a typosquatted package or a poisoned dependency — the firewall has no opinion on the difference between a legitimate package and a malicious one served from the same, permitted host.
- **Shared infrastructure blurs the allowlist's edges.** Many unrelated services sit behind the same CDN or reverse-proxy IP ranges. An allowlist built from resolved IPs can end up permitting more than the one hostname it was written for, simply because the DNS answer for an allowed name and the DNS answer for something else point at the same edge node.
- **The bootstrap window runs as root.** Firewall and DNS setup happen before privileges are dropped, because an unprivileged process cannot install `iptables`/`ipset` rules itself. That's a deliberately small window, but it is a window, and it exists precisely because process containment can't apply to the step that sets process containment up.
- **The home-directory volume is shared, persistent, and trusted by default.** Anything written under the agent user's home directory — a shell rc file, a global package install, a package manager's cache entry — survives across container runs and is picked up the next time that volume is mounted, by whatever project happens to run next. It's a smaller-scale version of the project-mount problem, in a place that's easy to forget is there at all.
- **A gateway's tunnel account is a real shell, not a forced command.** The `sshuttle`-based gateway model needs an interactive account capable of running a relay process, which rules out the usual hardening of locking an SSH account to a single forced command. The mitigation is the amount of mess — a disposable, single-purpose container with nothing else worth reaching on it — not elimination of the exposure.
- **Every gateway deployment needs a bootstrap path before the tunnel exists.** Reaching a gateway — whether a sibling container next door or a machine elsewhere — requires a real route out before the tunnel takes over that route, so a narrow allowance (one IP, or a handful of published edge addresses) is opened first. It's deliberately small and brief, but it's present in every gateway deployment this project ships, same-host included, not just distant ones — there's no zero-bootstrap option on offer.
- **None of this vets the image itself.** A read-only root filesystem, a non-root user, and a locked-down network all assume the container was built from trustworthy layers in the first place. A compromised base image, a poisoned build-time dependency, or a malicious plugin installed at build time sits inside every one of these boundaries, not outside them — this design constrains what a compromised *runtime* agent can reach, not what a compromised *build* can plant.
- **Configuration can quietly opt back out.** Setting the egress allowlist to allow everything disables the firewall outright, and an overly broad allowlist entry — a whole domain when one subdomain was meant — weakens it without looking like a mistake. The strength of this design is a property of how it's configured, not something the image guarantees on its own regardless of the flags it's started with.