---
icon: lucide/shield-alert
---

# Organisational HTTPS proxies and self-signed certificates

Deployments that sit behind an organisational HTTPS proxy performing TLS
interception (a self-signed or internal-CA certificate presented in place of
the real destination's certificate) require two independent pieces of
configuration inside the agent container itself — `claude-code`, `hermes`,
or any future agent image built on the same
[`AGENT_*`/`/etc/agent/*` contract](container-images/agent-gateway.md) (the
shared naming convention these images use for egress/gateway configuration:
environment variables prefixed `AGENT_*` and files mounted under
`/etc/agent/*`, covered in detail on the individual
[container image](container-images/index.md) pages).
This holds regardless of which egress mechanism is in use: the
[in-container allowlist](container-images/claude-code.md#in-container-allowlist)
or [gateway-client mode](container-images/claude-code.md#gateway-client-mode).

!!! note "Why gateway-client mode does not change this"
    `sshuttle`, used in gateway-client mode, operates at the network layer
    (L3/L4): it transparently tunnels whatever TCP connection a process
    already opened. It has no notion of HTTP, HTTPS, or TLS, and does not
    read `HTTP_PROXY`/`HTTPS_PROXY` or perform certificate validation.
    Both the proxy dial decision and the TLS handshake happen in the
    application process itself — inside the agent container — whether or
    not that connection is subsequently tunnelled through a gateway.

## Certificate trust

The organisational proxy's certificate (or the internal CA that issued it)
must be trusted by every process inside the agent container that makes
outbound HTTPS requests.

Two constraints shape how this can be done:

- The root filesystem runs `--read-only`, and images such as `claude-code`
  offer no `sudo` access at runtime.
- `update-ca-certificates` writes into `/etc/ssl/certs` and
  `/usr/local/share/ca-certificates`, both part of the read-only root
  filesystem.

Consequently, there is no runtime window in which the system trust store
can be updated. For anything that consults the system trust store (curl,
git, most OpenSSL-linked tooling), the certificate has to be installed
during the image build: the `.cer`/`.pem` file copied into
`/usr/local/share/ca-certificates/custom/`, referenced from
`/etc/ca-certificates.conf`, and `update-ca-certificates` run as root
before the image's final non-root layer.

### Downstream Dockerfiles

Baking a specific organisation's CA into the shared, tracked `claude-code`/
`hermes` images is undesirable, since it couples a general-purpose image to
one deployment and forces a rebuild whenever the certificate rotates. A
downstream build (supplying the certificate via build context or build
argument on top of the base image) is the more appropriate place for this
than the images maintained in this repository.

Concretely, this means a separate Dockerfile — outside this repository —
that starts `FROM claude-code:<tag>` (or `FROM hermes:<tag>`) and adds only
the `COPY`/`update-ca-certificates` layer on top, rather than modifying the
Dockerfile or build context of either image maintained here. Neither image
switches to a non-root user at the Dockerfile level (the privilege drop
happens in the entrypoint at container start, not at build time), so the
downstream Dockerfile can `COPY` the certificate and run
`update-ca-certificates` directly, without needing to reason about `USER`
switches back and forth. The result is a distinct, organisation-specific
image built on top of the unmodified base image, kept and versioned
wherever that organisation's other deployment-specific configuration
lives.

The downstream Dockerfile should not declare its own `ENTRYPOINT` or `CMD`.
`claude-code` sets `ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]` and
`CMD ["claude"]`; `hermes` sets the equivalent `ENTRYPOINT` pointing at its
own `entrypoint.sh`. These scripts perform the egress `iptables` setup,
the gateway-client `sshuttle` bootstrap, and the privilege drop to the
non-root user — all of which would be silently skipped if a downstream
`Dockerfile` overrode them. Adding only `COPY`/`RUN` instructions after
`FROM` leaves both directives inherited unchanged from the base image, so
the added layer is purely additive.

`FROM claude-code:<tag>` does not require the image to be published to a
public registry — Docker resolves `FROM` against the local image store
first, and only attempts a registry pull if no local image with that
name and tag exists. Since this repository does not publish images itself,
only Dockerfiles, the base image has to be built and tagged locally before
the downstream build can reference it, e.g.:

```sh
docker build --build-context shared=agent-images/shared \
  -t claude-code:local agent-images/claude-code
```

with the downstream `Dockerfile` then starting `FROM claude-code:local`,
built on the same Docker daemon (or a daemon that has that image loaded,
e.g. via `docker save`/`docker load`). For a downstream build pipeline
that lives in a separate repository, this typically means either vendoring
or pinning this repository so the base image can be built as a first step
before the downstream build runs, or pushing the locally-built base image
to a private/internal registry the organisation controls and referencing
that registry path in `FROM` instead — a public registry is never
required.

### Runtimes with their own certificate stores

Installing the certificate into the system trust store is not always
sufficient. Several language runtimes ship a bundled CA list and ignore
`/etc/ssl/certs` entirely unless told otherwise:

| Runtime / library | System store consulted by default? | What is needed |
|---|---|---|
| curl, git, most OpenSSL-linked CLIs | Yes | Nothing beyond the system store update |
| Node.js (`https`, `fetch`/undici) | No — uses its own bundled CA list | `NODE_EXTRA_CA_CERTS=/path/to/cert.pem` |
| Python (`requests`, stdlib `ssl`) | No — `requests`/`certifi` ship their own bundle | `SSL_CERT_FILE` and/or `REQUESTS_CA_BUNDLE` pointing at the certificate |

Since these are plain file paths rather than a system-wide store rebuild,
they do not require an image rebuild: the certificate can instead be
supplied as a read-only bind mount (analogous to the existing
`/etc/agent/gateway-key` mount) with the corresponding environment
variable pointing at the mounted path. This keeps an organisation-specific
certificate out of the image entirely, at the cost of needing to identify
every runtime/library in the agent's dependency tree that requires its own
pointer, since a single system-store update does not cover all of them.

## Proxy environment variables

The agent's own HTTP client(s) need to be told to route through the
organisational proxy: `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, and their
lowercase equivalents (`http_proxy`, `https_proxy`, `no_proxy` — some
tools only check one case). Unlike the certificate, these can be supplied
as ordinary environment variables at `docker run`/compose time, without
any image rebuild, since they do not require writing to the filesystem.

As with certificate trust, this has to be set on the agent container
itself in both egress modes, for the same reason: `sshuttle` tunnels
whatever connection the application already chose to make, so if the
application is not proxy-aware, it will simply dial the real destination
directly and bypass the proxy — a gateway sitting further down the tunnel
has no opportunity to inject proxy awareness that the application never
had.

### Node.js and Python may not honour these automatically

Setting the environment variables is necessary but not always sufficient,
because not every HTTP stack reads them automatically:

- **Node.js** — the core `http`/`https` modules and the global `fetch`
  implementation (undici) do **not** automatically honour `HTTP_PROXY`/
  `HTTPS_PROXY`. A Node-based agent needs an explicit proxy-aware
  dispatcher (e.g. undici's `ProxyAgent`/`EnvHttpProxyAgent` via
  `setGlobalDispatcher`), an env-based shim such as `global-agent`, or, on
  Node.js v22.21.0+/v24.0.0+, the `NODE_USE_ENV_PROXY=1` flag (or
  `--use-env-proxy`), which makes the built-in `fetch` parse and respect
  `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` — note this flag only affects
  `fetch()`, not the core `http`/`https` modules. Without one of these,
  the proxy environment variables will simply be ignored by anything
  using Node's built-in networking.
- **Python** — `requests` and the stdlib `urllib` honour the proxy
  environment variables by default (`trust_env=True`), so most
  `pip`/`requests`-based tooling works without extra configuration.
  This is not universal, however: some HTTP client libraries default to
  ignoring the environment (`aiohttp`, for instance, requires
  `trust_env=True` to be passed explicitly). Which HTTP client library a
  given Python-based tool uses needs to be checked rather than assumed.

In both cases, the practical implication is the same: setting the proxy
environment variables covers tools built on proxy-aware HTTP stacks, but
each runtime component in the agent's dependency chain needs to be
checked individually for whether it actually consumes those variables,
rather than assuming environment-variable configuration is universally
respected.
