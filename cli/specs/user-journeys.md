# User journeys

The onboarding CLI helps users configure, use, and maintain hardened coding-agent
environments through named profiles. Its user journeys cover the following
functional groups:

| Functional group | Main user interactions |
|---|---|
| Getting started | Check environment readiness independent of any profile, and discover the CLI's supported agents and their prerequisites before creating a profile. |
| Profile management | Create, list, inspect, edit, clone, and remove named profiles; export and import configuration packages for sharing and migration. |
| Environment configuration | Choose an agent, provider, authentication method, endpoint, and model; native agent configuration; tools; workspace behavior; agent home directory persistence and sharing scope; additional bind mounts; runtime environment variables; network access; and optional integrations. Review the resulting configuration and its implications. |
| Deployment management | Validate configuration, preview changes and their effects, prepare a deployment, check for updates, apply updates, inspect deployment history, and select an earlier deployment. |
| Agent use | Launch an interactive agent session in a chosen project, directly or through a shortcut; supply temporary options; inspect and explicitly stop active sessions. |
| Diagnosis and recovery | Understand effective settings, check prerequisites and authentication readiness for a named profile, explain network access, explicitly probe connectivity, and recover from failed or interrupted operations. |
| Resource retirement | Remove managed profile directories and clean up unused managed resources, with deletion of Docker resources and persistent agent data treated as separate, explicit actions. |

A **profile** describes desired configuration. A **deployment** records an applied
image and launch configuration. A **session** is an invocation of a deployment.
An **agent home directory** holds mutable agent state and has an explicit
persistence and sharing scope.

The journeys cover first-time setup, returning users, and noninteractive
automation. Detailed command names and syntax are specified separately in
`interface.md`.

## Initial runtime scope

The initial scope supports the real Docker executable. Support for alternative
container-runtime executables, compatibility wrappers, and aliases is deferred.
Profile creation and editing remain independent of Docker availability.

## Checking environment readiness

Users can check environment readiness before creating any profile. This check
is independent of any profile: it inspects Docker availability and version,
and other host prerequisites the CLI depends on, without requiring a named
profile as input.

Results distinguish failures, warnings, and checks not performed, following
the same reporting shape as profile diagnostics. Each finding states what was
checked, its result, and a suggested next action. The check does not create,
modify, or delete any profile or Docker resource.

If prerequisites are missing, the CLI explains what is missing and why it
matters, without attempting to install or configure host software itself.
Passing this check does not guarantee that every agent or provider works;
agent-specific and provider-specific requirements are checked separately
during profile creation, application, and diagnostics.

## Discovering supported agents

Users can list the agents supported by the installed CLI, independent of any
profile. The list identifies each agent and a short description of what
distinguishes it.

Selecting an agent from the list shows its supported providers and
authentication methods, the model roles it defines, prerequisites specific to
that agent, and the optional native-configuration items, software categories,
and integrations it supports. This is the same information surfaced when
choosing an agent during profile creation; discovery lets users review it
beforehand without starting a profile.

The supported-agent list reflects the CLI's installed version; agents added or
removed by a CLI update are reflected after updating the CLI itself.
Discovering agents does not require Docker and does not create, modify, or
delete any profile.

## Managed profiles

The CLI maintains operational profiles exclusively within its standard per-user
profiles directory. Users address profiles by unique names. Each profile occupies
its own directory containing `profile.toml` and profile-owned configuration
assets, such as native agent settings and CA certificates.

Ordinary profile operations do not accept external profile paths. Registering
an external profile for continued use in place is not supported. Importing a
configuration package is an explicit transfer into managed storage, not a
registration or a continuing link to the source.

Profile-owned assets are referenced relative to the managed profile directory.
They are distinct from the following runtime inputs:

| Runtime input | Meaning |
|---|---|
| Additional bind mount | A host file or directory explicitly exposed inside the container. Its source is external to the profile directory and checked when applying and launching. |
| Docker named volume | Docker-managed storage identified and inspected through Docker, rather than treated as a host filesystem path. |
| Workspace | The directory from which the user launches the contained agent, determined at launch time. |

## Creating a profile

Users choose a unique profile name and agent, then configure authentication,
tools, connectivity, and persistence through relevant questions. Advanced
settings are optional. Before saving, users can review and revise any section,
including configuration assets, writable locations, and permitted network access.
Cancellation leaves no partially created managed profile. Saving creates the
profile without deploying it and explains how to proceed.

When configuring credentials through the CLI, setup uses references by default.
Users may explicitly
enable encrypted credential storage and enter credentials through a deliberate
entry flow that does not echo their values. Reviews show references and storage
status, never credential values.

## Choosing agent authentication and provider setup

After choosing an agent, users choose either to complete its own authentication
or setup flow when launched, or to configure a provider endpoint and credential
source through the onboarding CLI. Agent-managed setup requires no endpoint or
credential values in the profile. The CLI explains remaining first-launch steps
and proposes the network access needed for that flow. Available choices are
described separately for each supported agent.

Existing authentication in a reused agent home directory may make another login
unnecessary. Missing CLI-supplied credentials must not block launch when users
have deliberately chosen agent-managed authentication.

## Configuring a provider endpoint and model

Users who choose CLI-configured provider setup select between the agent's
default vendor endpoint and a custom endpoint override. The default endpoint
needs only the credential already configured for it. A custom endpoint
requires a URL the user supplies — whether it points at an alternative hosted
provider, a local inference engine the user already runs, or any other
compatible endpoint — and its credential follows the same reference-only or
encrypted-storage policy as any other credential. The CLI never installs,
runs, or manages the target behind a custom endpoint.

Once an endpoint is chosen, users supply the model identifier it should use.
Available model slots depend on what the selected agent supports: some agents
accept a single model identifier, while others define multiple named roles,
such as a primary model alongside one or more lighter or background models.
The CLI shows which roles the selected agent supports before asking for
values, the same per-agent detail already surfaced during agent discovery.
Each slot is entered as free text; the CLI does not validate an identifier
against a live model catalog, and an accepted value does not guarantee the
endpoint actually serves that model.

The CLI translates the configured endpoint and model selections into whatever
mechanism the selected agent requires to use them, without exposing that
mechanism as a user choice.

## Configuring native agent configuration

For each native-configuration item — the core settings file, each MCP server
definition, each plugin, each skill, and each custom command — users choose to
import it from an existing host location, author it through CLI-guided
questions with agent-specific defaults, or leave it at the agent's own
built-in default. Both an import and CLI-guided authoring may be used within
the same profile for different items, but not combined for the same item, so
profile-owned content for a given item always has one clear origin.

Imported or authored native configuration becomes a profile-owned managed
asset, copied into the managed profile directory rather than referenced in
place. Later changes to the original host files do not alter the managed
copies; re-importing requires another explicit action. Review lists the
imported or authored items by kind and source, distinguishing profile-managed
native configuration from other profile-owned assets such as CA certificates.

Applying seeds each managed native-configuration item into the agent home
directory only where it does not already exist there. It never silently
overwrites an item the agent home directory already has, whether that item
was placed by a previous apply or written by the agent itself during use; the
agent home directory's copy becomes authoritative for that item once present.
This mirrors how image-installed optional software defers to versions already
installed in the persistent agent home directory.

Diagnostics identify where the agent home directory's native configuration
differs from the profile-managed version, without resolving the difference
automatically. Users who want to overwrite an item in the agent home directory
with its profile-managed version take an explicit, reviewed reseed action
scoped to that item; reseeding one item does not affect unrelated
native-configuration items or other agent home directory content.

Fresh and ephemeral agent home directories have no prior native configuration,
so applying seeds the full managed set on first use, as at initial deployment.

Imported or authored native configuration is stored as the agent's own literal
content, separate from the CLI's credential reference and encrypted-storage
system. CLI-guided authoring keeps credential values out of that content by
using the same reference mechanism as other CLI-configured credentials.
Imported content is opaque to the CLI and may contain embedded credentials,
such as inline MCP server tokens; its presence in a profile directory does
not make it safe to export or otherwise treat as free of secrets. This
distinction carries into export eligibility, covered under Sharing and
migration.

## Selecting image-installed software

Users review software provided by the selected image and optionally customise
system packages, npm packages, isolated Python CLI tools, and importable Python
libraries. While asking for input for each category, the CLI displays the
image-provided optional defaults as a list, explicitly indicating when there
are none. Users who supply no custom selection therefore know which defaults
will be installed.

For each category, users choose one of four explicit modes:

| Mode | Effective optional package selection |
|---|---|
| Keep defaults | Use the image-provided defaults. |
| Extend defaults | Use the image-provided defaults together with user-selected additions. |
| Replace defaults | Use only the user-supplied list instead of the image-provided optional defaults. |
| Set to none | Install no optional packages from this category. |

Categories without a custom selection keep their defaults. Required
infrastructure packages are separate and cannot be removed through any of these
modes, including set to none.

Review distinguishes image defaults from profile customisations, shows the
effective package lists, and explains which changes require rebuilding. Applying
installs selected software into the image. It does not silently expand runtime
network access or remove tools installed in the persistent agent home directory.
Diagnostics identify when home-installed tools take precedence over image-installed
versions.

## Choosing agent home directory persistence

By default, each profile uses a persistent agent home directory backed by a
named Docker volume. Users may instead select separate persistent agent home
directories per project, an ephemeral agent home directory per session, or an
explicitly selected existing Docker volume.

The review explains what persists and which sessions share that state, including
authentication and installed tools. Fresh or ephemeral agent home directories
may require authentication again.

Project identity must distinguish different project paths even when their
directory names match. Changing persistence mode does not silently copy,
migrate, or delete existing data.

## Configuring additional bind mounts

Users explicitly select additional host files or directories to expose inside
the container, specifying each source, container destination, and access mode.
Mounts are read-only by default; writable access requires an explicit choice.

Review identifies the exposed locations and explains that writable mounts allow
changes to the original host content. These mounts are distinct from the
launch-time workspace and Docker-managed agent home directory.

Applying and launching check that sources exist and have the expected type.
Conflicting destinations, including overlaps with CLI-managed mounts, produce
actionable errors. Missing sources are never silently created.

## Configuring runtime environment variables

Users can configure additional runtime environment variables using literal
non-secret values, references to host environment variables, or encrypted
credential references. The CLI passes only explicitly configured variables,
together with those required by its supported integrations. Review identifies
each source without exposing credential values. Environment values are supplied
at launch, not embedded in images.

Users may configure an external `.env` file as an environment source. The profile
stores its location, not its contents. Applying checks accessibility and
structural validity; launching reads the current contents. Changes to that file
affect subsequent launches without rebuilding the image.

The file is parsed as data and never executed as a shell script. Its values are
not displayed, copied into managed profile assets, embedded in images, or
included in exports. Export identifies the external dependency. Missing files
or invalid entries produce actionable errors before launch.

Conflicts with dedicated settings or other configured environment sources are
reported without exposing values: whichever single configured source defines
a given variable name is used, and two or more configured sources defining
the same name is always a reported conflict, regardless of which kinds of
source they are. This applies uniformly to the proxy-related variables —
`HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` — the same as any other name: a
`.env` file or a literal value may supply one of them only when the
corresponding dedicated proxy setting is not explicitly configured; if both
define it, the CLI reports a conflict. Containment controls remain restricted
to their dedicated settings.

Externally maintained `.env` files may contain plaintext credentials. The CLI
does not copy or persist those credential values itself.

## Configuring network access

Users review the network destinations required by their selected agent,
authentication method, provider, and optional integrations. The CLI explains the
purpose of each proposed destination and lets users accept or revise the proposed
access.

Additional development destinations, such as Git hosting and package registries,
are explicit choices. Selecting software for installation does not silently
grant runtime network access.

Users can inspect where restrictions are enforced and distinguish application
destinations from gateway bootstrap access. Broader access choices explain their
effect on containment. The review distinguishes configured access from
connectivity actually checked.

### Proxy and certificate configuration

Before the final network review, users indicate whether their environment
requires an HTTP(S) proxy. If so, they configure proxy addresses and bypass
destinations. Proxy credentials follow the agreed credential-reference or
encrypted-storage policy. SOCKS proxy support, including a `SOCKS_PROXY`
variable, is a deferred, low-priority consideration and is not part of this
version's proxy configuration.

Users can add custom CA certificates, individually or from a directory, when
required to trust the proxy or another configured endpoint. The CLI validates
the supplied certificate assets, rejects private-key material, and accepts
any valid certificate — not only those from a certificate authority, so a
single self-signed endpoint certificate can be trusted directly. An expired
certificate or a weak signature algorithm is flagged as a warning rather than
silently accepted or rejected on that basis alone. Accepted certificates are
copied into the managed profile directory. Custom CA trust is also
configurable without a proxy.

The review shows proxy configuration, bypass destinations, and added trust
certificates without exposing credentials. It explains that proxy bypass does
not bypass the egress policy, and distinguishes trust extended to a
certificate's issuer from trust extended to that certificate alone when the
accepted input is not a certificate authority.

Applying incorporates the certificates into the container's system trust
store by rebuilding the image; adding or replacing a certificate always
requires a rebuild. Environment-variable-based trust hints for specific tools
may supplement the system trust store but are never the sole mechanism.
Later changes to the original certificate files do not alter the managed
copies, the same one-time-copy convention used for native-configuration
imports; replacing managed certificates requires another explicit apply.
Connectivity checks distinguish proxy connection, authentication, and
certificate-trust failures where possible.

### Gateway configuration

Users choose whether to enforce egress through local workload filtering or an
existing supported gateway. Gateway setup collects connection details,
authentication references, trusted host identity, and required bootstrap
destinations.

The review distinguishes access needed to establish the gateway connection from
application traffic routed through it. It explains which policy the profile
controls and which policy is managed at the gateway.

Missing or conflicting settings are reported before applying. Gateway failure
must not silently fall back to unrestricted or direct application access.
Explicit connectivity checks distinguish gateway connection failures from
failures reaching destinations through it.

Configuring a profile to use a gateway does not provision or administer the
gateway itself.

## Configuring optional integrations

Users can enable optional integrations from a list scoped to the selected
agent; the set of available integrations depends on which the agent supports,
the same per-agent scoping shown during agent discovery. Every optional
integration is disabled by default. Enabling one is an explicit choice, never
inferred from other configuration.

Enabling an integration adds its required destinations to the network-access
review and its required environment variables or credentials to environment
and credential configuration, following the same reference-only or
encrypted-storage policy as other credentials. Review attributes each added
destination, variable, and credential to the integration that requires it,
distinct from values the user configured directly.

Some integrations require no more than destinations and environment values.
Others also affect deployment resource naming, such as image, container, or
data-volume names, or mount an agent's own configuration or collection
directories directly, rather than through the ordinary bind-mount or
native-configuration flows. For these, review discloses the resulting naming
scheme and which directories become mounted. Applying reports a conflict,
rather than silently choosing precedence, when an integration's required mount
collides with an explicitly configured bind mount, configuration mount, or
native-configuration import.

Integrations marked experimental require an explicit acknowledgment naming
them as experimental when first enabled, distinct from the ordinary enable
choice. Their description states what makes them experimental, such as
limited agent support or an unstable configuration shape.

## Editing a profile

Users select an existing profile by name and edit the whole profile or a chosen
section, with existing non-secret values populated. Credential fields show
references and storage status rather than stored values. Before saving, they review the proposed
changes and correct validation errors without losing unrelated answers.
Cancellation preserves the previously saved profile and its managed assets.
Saving updates the desired configuration without applying a deployment or
altering running sessions, and explains how to preview and apply the changes.

Editing a credential field follows this same review-before-save flow. Users
may change a reference's source, switch a credential between reference-only
and encrypted storage, or replace an encrypted credential's stored value with
a new one under the profile's current key, without unlocking or exposing the
value being replaced. Removing a credential clears its reference or stored
value; review identifies deployments or sessions that depend on it.

## Listing and inspecting profiles

Users list profiles with their names, agents, selected deployments, and unapplied
changes. Empty lists provide next steps; invalid profiles do not prevent others
from appearing. The same guidance appears whenever no profiles exist, regardless
of whether the CLI has been used before; the CLI does not track first-time use
as separate state. Guidance for an empty list points to discovering supported
agents and creating a first profile.

Inspection explains configuration sources, managed assets, and external
dependencies, distinguishing desired configuration from the selected deployment.
Credential references and storage status may appear; values never do.

Both operations remain available without Docker, clearly identifying information
that is unavailable or has not been checked.

## Cloning a profile

Users clone an existing profile under a new unique name, copying its desired
configuration and managed configuration assets for independent editing. The clone
starts without a deployment or deployment history.

The clone uses a separate agent home directory by default. Reusing an existing
Docker volume requires an explicit choice. External bind-mount references are
retained and highlighted because they still expose the same host files or
directories. The workspace remains determined at launch.

Users choose separately whether to retain each credential reference and each
stored encrypted credential. The CLI identifies credentials by name and purpose
without displaying their values. Retaining a reference copies its definition.
Retaining an encrypted credential requires the user to supply the source
decryption key and successfully unlock it, then freshly encrypt it for the clone.
The CLI does not merely copy ciphertext.

One destination encryption key applies to all retained encrypted credentials in
the cloned profile. Users supply a destination key, which may be the same value
as the source key or a newly configured key for the clone. Key scope is
strictly per-profile, not per-user or per-credential. A source key may unlock
multiple selected credentials during the operation without repeated entry.

Skipped credentials are identified as requiring configuration where necessary.
Failure to unlock or encrypt a credential does not silently omit it or save
plaintext. Users may retry, explicitly skip it, or cancel cloning. Noninteractive
cloning requires explicit credential selections and the necessary key sources;
unresolved choices fail with actionable instructions.

Users review their choices before saving. Cancellation leaves no partially
created profile. Successful cloning does not build images or launch an agent.

## Removing a profile

Users select a profile and review its managed configuration, encrypted credentials,
and associated resources. They choose independently whether to delete eligible
Docker images and named volumes. Resources referenced by any container, another
profile, or a retained deployment that will remain are protected from deletion.
If Docker cannot be inspected, Docker-resource deletion is unavailable.

The CLI never deletes external bind-mount sources. Because the CLI never
stores a profile's passphrase or its derived encryption key in its own
managed storage, removal has no such key material of its own to delete; the
profile's non-secret derivation parameters are removed with the rest of the
profile directory. If the profile has a cached passphrase in the host's
OS-managed credential store, removal deletes that cache entry, since key
scope is strictly per-profile and the entry is exclusively owned by the
removed profile; if the credential store cannot be inspected, cache deletion
is unavailable and is reported as such rather than silently skipped. It also
prunes the profile's shortcut from the generated shortcuts file.

Before confirmation, the CLI lists exact deletion targets, retained resources,
and any persistent-data loss. Active sessions belonging to the profile block
removal. Cancellation preserves the profile and its resources.

## Cleaning up unused resources

Users inspect unused CLI-managed Docker resources and select eligible images or
named volumes for deletion. The preview identifies exact resources, their known
associations, and any persistent-data loss.

Resources referenced by containers, profiles, or retained deployments are
protected. Users must explicitly retire a retained deployment before its
otherwise-unused image becomes eligible for cleanup. The currently selected
deployment cannot be retired.

Cleanup requires explicit confirmation and Docker inspection. It never deletes
external bind-mount sources, workspaces, or encryption keys. If deletion partly
fails, the result identifies what was removed, what remains, and why.

## Validating a profile

Users validate a named managed profile to check its structural correctness
without contacting Docker or changing any file. Validation parses
`profile.toml`, rejects unknown fields, and checks field types, required
combinations, and mutually exclusive settings, such as native imports and
configuration mounts.

Validation checks the shape of credential fields without resolving them: it
confirms a reference or an encrypted-storage entry is internally consistent,
but does not contact the referenced source, unlock encrypted storage, or
require the encryption key. It does not check Docker availability, network
reachability, or provider authentication; those checks belong to preview,
apply, and diagnostics.

Preview, apply, and export always validate as part of their own flow;
standalone validation lets users, or automation such as CI, check a
profile's correctness independently of any of them, without depending on
Docker being available. It never modifies the profile or its managed
assets.

Results distinguish errors that block deployment from warnings that do not. A
profile with only warnings is still valid.

## Previewing a deployment

Users select a profile and preview the actions needed to prepare or update its
deployment. The preview identifies image builds, launch-configuration changes,
writes to the agent home directory, and changes to network access or writable
mounts. It explains effects on future versus existing sessions and what
deployment rollback can restore.

Deployment previews automatically inspect Docker and compare its resources with
the profile and recorded deployment metadata. Inspection does not modify
resources, start containers, or test provider connectivity. The preview
distinguishes configuration changes from runtime discrepancies, and verified
facts from assumptions and unresolved dependencies.

If Docker cannot be reached, the CLI explains why and offers a limited preview
using recorded metadata. Such a preview clearly identifies unverified resources
and must not claim deployment readiness. Live resource inspection alone does
not establish that authentication, network access, or the agent works. The result
explains the next action.

## Applying a deployment

Users apply a named profile to prepare or update its deployment. The CLI checks
Docker and required inputs, refreshes the deployment preview, and asks users to
confirm the proposed changes before making them.

It builds or reuses the required image, prepares the specified configuration and
storage, and selects the deployment after successful preparation. Applying does
not launch an agent or stop existing sessions.

The result identifies the selected deployment and explains how to launch it. If
preparation fails, the CLI reports completed actions, any persistent-data changes,
and recovery steps without presenting the deployment as successfully applied.

Noninteractive use requires explicit confirmation options in place of prompts.
The confirmation contract and remaining syntax decisions are tracked in
[interface.md](interface.md).

## Checking for and applying updates

Users check for updates relevant to a named profile. Results distinguish updates
to the onboarding CLI, image recipes, and image-installed agents or tools, and
identify where availability cannot be determined.

Checking does not change the profile or deployment. Users select available
deployment updates, review their effects, and apply them through the normal
preview and confirmation workflow. Updating the onboarding CLI is a separate
action.

A successful deployment update retains the previous deployment for rollback and
affects subsequent launches. It does not stop running sessions or automatically
replace tools installed in the persistent agent home directory.

## Deployment history and rollback

Users inspect retained deployments for a profile, including creation times,
image identities, change summaries, and the currently selected deployment.

Users choose a retained deployment to restore, with the immediately previous
deployment available as a convenient choice. The CLI checks Docker and required
resources, previews the changes affecting future launches, and requests
confirmation before changing the selection.

Rollback restores the selected image and recorded launch configuration. It does
not rewrite the desired profile, undo writes to the agent home directory or
workspace, or alter running sessions. Differences between the desired profile
and restored deployment remain visible.

If required resources are missing, the CLI explains the problem and preserves
the current selection.

## Launching an agent

Users launch the deployment selected for a named profile from the directory they want to
work in. That directory becomes the workspace. Launch is available directly
through the CLI and through a generated shell shortcut, with consistent behavior.

Before launch, the CLI checks Docker, resources of the selected deployment, required
bind-mount sources, and credential availability. It identifies the deployment,
workspace, and agent home directory persistence and sharing scope.

If the profile has unapplied changes, the CLI reports them and launches the
selected deployment without silently applying those changes. If no deployment
has been prepared, it explains how to apply the profile first.

The agent remains interactive and attached to the terminal. Users can pass agent
arguments for that invocation without modifying the profile. Terminal input,
signals, and the session exit status are preserved.

On exit, the workspace and persistent agent home directory retain their changes
according to the configured persistence policy. Exiting does not remove the
profile or its deployment. Routine launch requires no additional confirmation
prompt; missing prerequisites produce actionable errors.

## Generating and using shell shortcuts

Applying or rolling back a profile's deployment generates or refreshes a
per-profile shell shortcut, alongside the profile's own entry in a single
generated shortcuts file. Users source that file once from their shell
startup so shortcuts become available in new shells; sourcing it again after
a refresh picks up the change.

A shortcut resolves the profile's current state at invocation time rather
than freezing it at generation time: it evaluates the directory it is invoked
from as the workspace and launches the profile's currently selected
deployment, the same as launching directly through the CLI. Regeneration on
apply or rollback keeps the shortcut in step with changes that affect which
profile it maps to or how it is named.

Shortcuts forward arguments to the agent the same way direct launch does.
They do not accept arbitrary container-runtime options; an intentional
one-off override beyond what a shortcut and direct launch already support is
out of scope for this journey.

Removing a profile also prunes its shortcut from the generated shortcuts
file, so no stale shortcut for a deleted profile remains available in a
freshly sourced shell. Invoking a shortcut for a profile that was removed
without re-sourcing the file, such as in an already-open shell, reports an
actionable error rather than acting on a Docker resource that may no longer
exist.

## Inspecting and force-terminating sessions

Users list active CLI-managed sessions and select one to inspect its agent,
profile name and optional description, deployment, workspace, container identity,
start time, elapsed runtime, and current Docker-reported state. Selection does
not change the session. Docker-reported state does not establish agent
responsiveness. Docker unavailability is reported rather than presented as an
empty session list.

Normal session exit happens through the agent in its attached terminal. The
session manager offers an explicit force-termination action for an unresponsive
or otherwise unrecoverable session. Before proceeding, it identifies the exact
container and warns that unsaved work or in-progress writes may be lost or
interrupted.

Force termination does not delete the profile, deployment, workspace, or
persistent agent home directory.

## Providing credentials

Users choose between runtime credential references and optional encrypted
credential storage. Without encrypted storage, the CLI persists references only
and obtains required values from the configured external source at launch.

Users opting into encrypted storage configure an encryption key for that
profile. Key scope is strictly per-profile: there is no shared, CLI-managed
key spanning multiple profiles. Unlocking material stays outside profile
directories and exports. At launch, the CLI unlocks and supplies only the
credentials required by the selected agent; it never supplies the encryption
key to the container. Missing keys or failed decryption do not trigger plaintext
storage as a fallback.

Whether a value came from a reference or from encrypted storage, the CLI
delivers it to the container only through a channel that does not expose it
outside the container: never as a container-runtime command-line argument,
image build argument, or image layer, and never visible in container
inspection output or CLI logs. The default delivery mechanism is a
memory-backed file mount the container can read at startup; environment-variable
delivery is used only when the selected agent has no file-based way to read a
credential. Review identifies which delivery mechanism applies without
exposing values.

These guarantees govern the onboarding CLI. Agents may persist credentials or
login tokens in their agent home directories. Encryption at rest does not conceal
credentials from the agent that needs to use them. The approved policy and
remaining design decisions are recorded in [security.md](security.md).

## Rotating a profile's encryption key and recovering from key loss

Users can rotate the encryption key protecting a profile's stored credentials.
Rotation unlocks the profile's stored credentials with the current key and
re-encrypts them under a new key value; it affects only that profile.

Before rotation, the CLI reports every affected credential and requires
confirmation. Cancellation leaves existing encrypted storage unchanged. If a
credential cannot be unlocked during rotation, the CLI reports the failure and
leaves the profile's encrypted storage under its original key rather than
partially rotating it or discarding the unreadable value.

If the key protecting a profile's encrypted credentials becomes permanently
unavailable, the CLI cannot recover the values it protects. Users may
explicitly discard the affected encrypted credentials and reconfigure them,
choosing reference-only or freshly encrypted storage through the same flow
used when first providing credentials. Discarding requires confirmation that
identifies exactly which credentials are lost. The CLI never substitutes a
different key or treats an unavailable key as an empty credential.

The encryption key is symmetric and is derived ephemerally from a
user-supplied passphrase; the CLI does not generate the passphrase and does
not persist the passphrase or the derived key in its own managed storage.
Users may explicitly opt in, per profile, to caching the passphrase in the
host's OS-managed credential store so it need not be retyped at every unlock.
This caching ties unlocking to the host user's session and is unavailable in
environments without one, including many noninteractive and CI environments;
passphrase entry through a reference remains available there. Rotation
updates a cached passphrase to the new value on success and leaves it
unchanged if rotation fails or is cancelled. The CLI never copies a cached
passphrase into profile directories or exports. Authenticator- or
passkey-based key derivation is deferred to a future version. Detailed
key-derivation and OS-credential-store integration mechanics remain to be
specified in [security.md](security.md).

## Diagnosing a profile

Users diagnose a named profile to understand problems with Docker availability,
configuration, deployment resources, bind mounts, credential availability, and
integrations. Each finding states what was checked, its result, and a suggested
next action. Missing credentials are distinguished from authentication rejected
by a provider.

Diagnostics automatically inspect relevant Docker resources without modifying
them. Checks that start a temporary container or contact an external endpoint
require explicit selection. Network checks use the relevant container environment
and never relax its restrictions to make a check pass.

Results distinguish failures, warnings, and checks not performed. Diagnosis does
not automatically repair configuration or resources; it explains the appropriate
recovery action.

## Recovering from failed or interrupted operations

Every mutating operation — creating, editing, cloning, importing, or removing
a profile; applying a deployment or rolling back; cleaning up unused
resources; and rotating an encryption key — records an in-progress marker
before changing any state, scoped to the profile it targets, or to the
resource set being changed for cleanup. The marker is cleared when the
operation finishes, whether it succeeds or fails cleanly. A stale marker left
by a process that was killed or a host that crashed before the operation
could finish or clean up is distinct from an ordinary in-app failure, which
is already reported directly to the user at the time it happens.

Any command invoked against a profile with a stale marker reports the
interrupted operation explicitly, rather than proceeding as though the
profile were in a normal state or failing with an unrelated error. Diagnosing
a profile surfaces the same finding. The report identifies which operation
was interrupted and, where determinable, what it had completed before
stopping.

The standard recovery action is to re-run the same command that was
interrupted. Operations are designed to be safe to retry from an in-progress
state: re-running either completes the interrupted work or reports what
remains inconsistent, building on how each operation already handles a clean
failure without corrupting state — clean cancellation for creating, editing,
cloning, importing, and removing a profile; original-key retention for key
rotation; and identified partial results for cleanup.

While a marker shows an operation in progress, a second mutating operation
that would target the same profile, or an overlapping resource set for
cleanup, is rejected with an actionable error instead of running
concurrently. This applies whether the first operation is still genuinely
running or was left stale by an interruption; a rejected concurrent attempt
does not itself clear a stale marker.

Docker resources left behind by an interrupted apply, such as a partially
built image, surface through the same unused-resource cleanup used for
retired deployments. They are not removed automatically.

## Sharing and migration

Configuration-package export and import belong to the initial scope. The
concrete package format remains to be specified in
[interface.md](interface.md); this journey describes it only as a
configuration package.

Users export a managed profile to share its configuration or transfer it to
another installation. The package contains `profile.toml`, CLI-authored
native-configuration items, and other eligible profile-owned assets such as CA
certificates. It identifies external bind-mount dependencies without copying
their contents. Workspace contents, Docker volume contents, deployment
history, credentials (including encrypted credentials), and encryption keys
are excluded.

Imported native-configuration items are excluded from export by default,
because their content is opaque to the CLI and may embed credentials or other
secrets. Users may explicitly opt each imported item into an export; doing so
requires an acknowledgment that its content was not verified secret-free. This
follows the same per-item origin the CLI already tracks for native-configuration
items: CLI-authored items are export-eligible because the CLI controls their
structure and keeps credentials out through the reference mechanism; imported
items are not, unless the user takes on that responsibility explicitly.

Users import a package to create an independently managed profile. Import
validates the package and identifies dependencies requiring local
configuration before deployment. Import derives a default profile name from
the package; a name that collides with an existing local profile prompts for
a different name interactively, and noninteractive import fails with an
actionable error on collision unless an explicit destination name was
supplied up front. Subsequent changes to, or loss of, the package source do
not affect the imported profile. External runtime dependencies may still be
required; importing configuration does not make the environment
self-contained.

Credential exclusion from an export is enforced structurally: the package is
built from a fixed set of CLI-defined fields and asset kinds classified as
exportable in the CLI's own schema, never from a list a profile could add to
or edit. Export first validates the profile the same way preview and apply
do, so a profile with an unrecognized field is rejected rather than partially
exported. This structural guarantee does not extend to opted-in imported
native-configuration content, which the CLI does not scan for embedded
credentials; the required acknowledgment is the only safeguard for that
content, not a verification claim.

## Deferred backup and restore

CLI-managed backup and restore are outside the initial scope. Their scope and
recovery guarantees require a later decision, including treatment of mutable
agent home directory contents, authentication state, Docker resources, and
consistency while sessions are active.

Users may copy profile directories with external filesystem tools. Such copies,
and configuration-package exports, do not constitute a CLI guarantee of complete
environment backup or restoration.
