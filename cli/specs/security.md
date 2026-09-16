# Security requirements

This document records approved requirements as they are agreed. It is not yet a
complete security specification or a claim about the current implementation.

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

Encrypted storage supports a user-level default key and optional per-profile key
overrides. Configuration stores key references, not unlocking material. Unlocking
material must remain outside managed profile directories and exports.

Key scope is per-user or per-profile, not per-credential. One effective
encryption key applies to the stored credentials of a profile.

A shared key simplifies operation but compromise or loss affects every credential
protected by it. Per-profile keys permit independent access and rotation, but
provide separation only to the extent that the keys are protected independently.

An established encryption or secret-store mechanism must be selected during
detailed security design. The mechanism, key provisioning and unlocking flows,
rotation, and handling of key loss remain to be specified.

## Credentials during cloning

Cloning requires a separate retain-or-skip choice for each credential reference
and each stored encrypted credential. Credential values must not be displayed.
Retaining a reference copies its definition without copying an external secret.

To retain an encrypted credential, the user must supply the source decryption key
and successfully unlock it. The CLI then freshly encrypts it for the destination
profile rather than copying ciphertext. The destination uses one user-supplied
key, which may be the source key, or the configured user-default key. A source key
may be reused within the cloning operation without repeated entry.

Decryption or encryption failures must not cause silent omission or plaintext
persistence. Users may retry, explicitly skip the credential, or cancel. Required
credentials skipped during cloning must be identified as needing configuration.
Cancellation must leave no partially created profile. Noninteractive cloning
requires explicit credential selections and necessary key sources; unresolved
choices must fail with actionable instructions.

## Keys during profile removal

Profile removal must never offer to delete or delete the user-level encryption
key. It removes the deleted profile key reference. Deletion of profile-level key
material may be offered only when the CLI manages that material and establishes
that it is exclusively owned by the removed profile. Shared keys and externally
managed key material must remain untouched.

Whether the CLI ever manages key material, rather than only referencing
user-provided keys, remains to be specified. This conditional deletion policy
does not establish a key-storage mechanism.

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
without exposing values. Containment controls must remain restricted to their
dedicated configuration fields. `.env` may provide `NO_PROXY` only when bypass
destinations are not explicitly configured in the profile; otherwise report a
conflict. This does not permit bypassing egress restrictions.

## Network and certificate trust

Proposed network destinations must be reviewable with their purposes. Additional
development destinations require explicit selection; package installation choices
must not silently expand runtime egress. Review must distinguish application
destinations from gateway bootstrap access and explain broader access choices.

Proxy credentials follow the same reference-only or opt-in encrypted-storage
policy as other credentials. Reviews must not expose their values. Proxy bypass
must not be presented as bypassing the egress policy.

Custom CA inputs must be validated and rejected if they contain private-key
material. Accepted certificates become managed profile assets. Review must explain
the extension of trust to added certificate issuers. Custom CA trust must be
configurable independently of proxy use. Detailed validation and deployment trust
integration remain to be specified.

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
How credential exclusion is enforced for those assets remains to be specified.
