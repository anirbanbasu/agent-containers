# Security requirements

This document records approved requirements as they are agreed. It is not yet a
complete security specification or a claim about the current implementation.

## Threat model

[Containment philosophy](../../docs/containment-philosophy.md) and
[security assessments](../../docs/security-assessment.md) define the adversary
model for the *running container*: what a compromised, in-container agent can
reach, and the boundaries that limit it. This document assumes that model and
does not restate it. The onboarding CLI is a separate actor in a different
position: it runs on the host, outside any container boundary, with authority
over profile directories, credential references and encrypted storage, key
material, the software and native-configuration selections baked into an
image, and configuration-package export and import. This section scopes the
CLI's own threat model and states how its decisions relate to limitations
already named for the container.

In scope: the confidentiality of credential values and encryption keys across
CLI storage, display, export, and delivery; the integrity of what the CLI
seeds into an image or an agent home directory; and whether CLI-mediated
transfers, such as cloning or configuration-package export, can leak
credential values or unvetted content across a trust boundary the user did not
intend to cross.

Out of scope: kernel, Docker daemon, and host operating-system security; the
in-container containment mechanics themselves (non-root execution, read-only
root filesystem, capability dropping, egress filtering), which remain owned by
containment-philosophy.md; and vetting the contents of upstream base images,
packages, or registries for vulnerabilities or malice.

Several requirements below exist specifically to close, or to knowingly leave
open, a limitation already named in containment-philosophy.md's "Known
limitations":

- **"None of this vets the image itself."** The CLI's software-selection and
  native-configuration-import flows are the actual mechanism by which
  build-time trust is established. This document does not yet specify any
  vetting of imported native-configuration content or user-supplied package
  lists before they are seeded into a profile or an image; imported content is
  treated as opaque, and the CLI relies on the user, not on scanning, to judge
  its trustworthiness.
- **"Any credential handed to the agent is a bridge, not a breach."** The
  runtime delivery mechanism below (a memory-backed file mount in preference
  to environment variables) narrows how a credential value can leak from the
  delivery channel itself; it does not, and cannot, restrict what an agent
  legitimately does with a credential once delivered.
- **"The home-directory volume is shared, persistent, and trusted by
  default."** The CLI's agent-home persistence choices and its
  never-overwrite native-configuration seeding behavior determine what
  persists into that trusted, shared volume across sessions and, for
  per-project or shared modes, across projects.

Where a requirement below states that something "remains to be specified,"
its eventual design must be evaluated against this threat model: what host-side
actor or transfer it protects against, and which named limitation, if any, it
narrows.

## Credential output and entry

The onboarding CLI must not display credential values in its output, including
configuration inspection, reviews, diagnostics, or errors. It may display
credential references and storage status. Credential entry for optional encrypted
storage must be deliberate and must not echo the entered value.

## Credential storage

The default mode persists credential references only, such as environment-variable
names. At launch, the CLI obtains required values from the configured external
source and passes only those needed by the selected agent.

Encrypted credential storage is opt-in. When enabled, credential values are
stored encrypted and separately from ordinary profile configuration. The CLI
must not persist plaintext credential values. A missing key or failed decryption
must never cause plaintext storage as a fallback.

## Encryption key scope

Encrypted storage uses one encryption key per profile, configured when a user
first opts into encrypted storage for that profile.

Key scope is strictly per-profile, not per-user or per-credential. One
effective passphrase applies to all stored credentials of a profile. The CLI
does not track or manage any shared, cross-profile key. Users who want to
reuse the same underlying passphrase across multiple profiles may do so as
their own choice; the CLI does not treat that reuse as a shared entity subject
to fan-out rotation or shared-ownership deletion rules.

The key is symmetric and is derived ephemerally from a user-supplied
passphrase through a key-derivation function. The CLI must not generate,
store, or export the passphrase or the derived key itself, and must not offer
to generate a passphrase on the user's behalf. Configuration stores only the
non-secret parameters needed to reproduce the derivation, such as a salt and
the function's cost parameters; these are not unlocking material on their own,
and their presence in the profile directory does not permit decryption
without the passphrase. The passphrase is supplied by the user at the point
it is needed — entered interactively without echoing, or, for noninteractive
and CI use, obtained from an external source through the same reference
mechanism used for other credentials. Users may explicitly opt in, per
profile, to caching the passphrase in the host's OS-managed credential store
so it need not be retyped at every unlock. This caching is disabled by
default, requires a choice separate from opting into encrypted storage
itself, and is available only where an unlockable host session exists; it is
unavailable in many noninteractive and CI environments, where passphrase
entry through a reference remains the required path and must keep working
without it. The CLI never copies a cached passphrase into profile directories
or exports, and treats a cache entry as exclusively owned by the profile that
created it. Outside such an explicit cache entry, the CLI does not otherwise
persist the passphrase or the derived key in its own managed storage —
profile directories, exports, or any other file it directly controls.

Authenticator- or passkey-based key derivation is deferred to a future
version and is not part of this version's key-management design; it must not
be assumed available. The specific key-derivation function and its
parameters, and the OS-credential-store integration per platform, remain to
be specified during detailed security design.

## Key rotation and recovery

Users can rotate a profile's encryption key, unlocking with the current key
and re-encrypting that profile's stored credentials under a new key value.
Rotation affects only the profile it is performed on.

The CLI must report every affected credential before rotation and require
confirmation. A credential that cannot be unlocked during rotation must cause
the profile's encrypted storage to remain under its original key; rotation
must not partially apply or discard the unreadable value.

A permanently unavailable key must not be treated as an empty credential, and
the CLI must not substitute a different key. Recovery is limited to explicitly
discarding the encrypted credentials it protects and reconfiguring them
through the ordinary credential-configuration flow, choosing reference-only or
freshly encrypted storage. Discarding requires confirmation that identifies
exactly which credentials are lost.

If the profile has a cached passphrase in the OS-managed credential store,
successful rotation replaces it with the new passphrase; a rotation that
fails or is cancelled must leave any existing cache entry unchanged, the same
as it leaves encrypted storage under its original key. Discarding a
profile's encrypted credentials after permanent key loss also clears any
cached passphrase for that profile, since it can no longer unlock anything
meaningful.

## Credentials during cloning

Cloning requires a separate retain-or-skip choice for each credential reference
and each stored encrypted credential. Credential values must not be displayed.
Retaining a reference copies its definition without copying an external secret.

To retain an encrypted credential, the user must supply the source decryption key
and successfully unlock it. The CLI then freshly encrypts it for the destination
profile rather than copying ciphertext. The destination profile uses one
user-supplied key, which may be the same value as the source key or a newly
configured key for the clone. A source key may be reused within the cloning
operation without repeated entry.

Decryption or encryption failures must not cause silent omission or plaintext
persistence. Users may retry, explicitly skip the credential, or cancel. Required
credentials skipped during cloning must be identified as needing configuration.
Cancellation must leave no partially created profile. Noninteractive cloning
requires explicit credential selections and necessary key sources; unresolved
choices must fail with actionable instructions.

## Keys during profile removal

The CLI never stores a profile's passphrase or its derived encryption key in
its own managed storage, so profile removal has no such material to delete
there; the non-secret derivation parameters are removed as ordinary profile
configuration, along with the rest of the profile directory, without a
separate confirmation.

If the profile has a cached passphrase in the host's OS-managed credential
store, removal deletes that cache entry, since key scope is strictly
per-profile and the entry is exclusively owned by the removed profile. If the
credential store cannot be inspected, such as when no unlockable host session
exists, cache deletion is unavailable and the CLI must report that rather
than silently skip it or claim it as done. A passphrase a user chooses to
remember or record themselves, outside any CLI-managed cache, is entirely
their own responsibility and outside the CLI's control.

## Runtime delivery and limits

The CLI unlocks encrypted credentials for launch and delivers only the values
required by the selected agent. It must never pass the encryption key into the
agent container.

Resolved credential values, whether reference-resolved or encrypted-storage-resolved,
must reach the container only through a channel that does not expose them outside
it: never as a container-runtime command-line argument, an image build argument,
or an image layer, and never visible in container inspection output or CLI logs.
The default delivery mechanism is a memory-backed file mount the container can
read at startup; environment-variable delivery is used only when the selected
agent has no file-based way to read a credential. This requirement applies
uniformly regardless of credential source. External credential source precedence
remains to be specified.

The prohibition on plaintext persistence applies to the onboarding CLI. An agent
may persist credentials or login tokens in its own agent home directory. The CLI
must not imply that its storage policy guarantees the absence of plaintext
credentials throughout the agent environment. Encryption at rest protects locked
stored credentials; it does not hide usable credentials from the receiving agent.

## Runtime environment sources

Literal profile environment values are limited to non-secret values. Sensitive
values use runtime references or the approved encrypted-storage mechanism.
Only explicitly configured environment variables and variables required by
supported integrations are passed at launch. Environment values must not be
embedded in images.

External `.env` files may contain plaintext credentials. The CLI stores the
file reference only, validates accessibility and structure during apply, and
reads current contents at launch. It must parse the file as data and never
execute it as a shell script. Values must not be displayed, copied into managed
profile assets, or included in exports. Export identifies the external dependency.

Conflicts between environment sources or dedicated settings must be reported
without exposing values: whichever single configured source defines a given
variable name is used, and two or more configured sources defining the same
name must always be reported as a conflict, regardless of which kinds of
source they are. Containment controls must remain restricted to their
dedicated configuration fields. This applies uniformly to the proxy-related
variables — `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` — the same as any
other name: `.env` may provide one of them only when the corresponding
dedicated proxy setting is not explicitly configured; otherwise report a
conflict. This does not permit bypassing egress restrictions.

## Network and certificate trust

Proposed network destinations must be reviewable with their purposes. Additional
development destinations require explicit selection; package installation choices
must not silently expand runtime egress. Review must distinguish application
destinations from gateway bootstrap access and explain broader access choices.

Proxy credentials follow the same reference-only or opt-in encrypted-storage
policy as other credentials. Reviews must not expose their values. Proxy bypass
must not be presented as bypassing the egress policy. SOCKS proxy support is
deferred to a future version and is out of scope for this document.

Custom CA inputs must be validated and rejected if they contain private-key
material. Validation otherwise accepts any parseable X.509 certificate, not
only those with a CA basic constraint, since rejecting a self-signed leaf
certificate would block trusting a single endpoint that no certificate
authority backs. An expired certificate or a weak signature algorithm must be
flagged as a warning, never silently accepted or rejected on that basis
alone.

Accepted certificates become managed profile assets and are incorporated into
the container's system trust store at image build time; adding or replacing
one requires a rebuild. Environment-variable-based trust hints for specific
tools may supplement the system trust store but must never be the sole
mechanism, since any single variable's tool coverage is partial. Replacing a
managed certificate follows the same one-time-copy convention as
native-configuration imports: the managed copy is authoritative once
accepted, changes to the original file do not propagate, and updating
requires another explicit apply.

Review must explain the extension of trust to added certificate issuers, and
must distinguish that from trust extended to a single certificate when the
accepted input is not a certificate authority. Custom CA trust must be
configurable independently of proxy use.

## Gateway enforcement

Gateway configuration must include connection details, authentication references,
trusted host identity, and required bootstrap destinations. Missing or
conflicting settings must be reported before applying.

Review must distinguish bootstrap access from application traffic and identify
which policy is controlled by the profile and which is managed at the gateway.
Gateway failure must not silently fall back to unrestricted or direct application
access. Explicit connectivity checks must distinguish gateway connection failures
from failures reaching destinations through the gateway.

Profile configuration does not provision or administer the gateway itself.

## Additional bind mounts

Additional host file and directory exposure requires explicit source and
destination selection. Bind mounts are read-only by default; writable access
requires an explicit choice and review must explain the ability to change
original host content.

Apply and launch must check that sources exist and match the expected type.
Conflicting destinations, including overlaps with CLI-managed mounts, must
produce actionable errors. Missing sources must not be silently created.

## Configuration package boundary

Configuration export/import excludes credential values, including encrypted
credentials, and encryption keys. Native configuration assets must not be assumed
safe to export merely because they are stored in a managed profile directory.

CLI-authored native-configuration items are eligible for export by default,
since the CLI controls their structure and keeps credential values out through
the reference mechanism. Imported native-configuration items are excluded from
export by default because their content is opaque to the CLI; including one
requires an explicit per-item opt-in and an acknowledgment that its content was
not verified secret-free.

Credential exclusion is enforced structurally, not by content inspection.
Export builds a package from a fixed, non-configurable allowlist of
CLI-defined fields and asset kinds, classified as exportable or
credential-bearing in the CLI's own schema; no profile can add, remove, or
reinterpret an entry in that classification, and export must never fall back
to excluding by pattern or by name at runtime. Export requires the profile
to validate successfully first, the same as preview and apply; because
validation already rejects unknown fields, a profile can never contain a
field the CLI's export classification does not already recognize.

This structural guarantee does not extend to opted-in imported
native-configuration content, which remains opaque to the CLI. The CLI must
not attempt to scan such content for embedded credentials before export — a
scan that misses something would let the required acknowledgment be read as
a verification it is not. Enforcement for that content is the explicit
per-item acknowledgment alone.
