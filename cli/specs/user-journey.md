# User journeys

The onboarding CLI helps users configure, use, and maintain hardened coding-agent
environments through named profiles. Its user journeys cover the following
functional groups:

| Functional group | Main user interactions |
|---|---|
| Profile management | Create, list, inspect, edit, clone, and remove named profiles; export and import configuration packages for sharing and migration. |
| Environment configuration | Choose an agent, provider and authentication method, tools, workspace behavior, agent home directory persistence and sharing scope, network access, and optional integrations. Review the resulting configuration and its implications. |
| Deployment management | Validate configuration, preview changes and their effects, prepare a deployment, check for updates, apply updates, inspect deployment history, and select an earlier deployment. |
| Agent use | Launch an interactive agent session in a chosen project, directly or through a shortcut; supply temporary options; inspect and explicitly stop active sessions. |
| Diagnosis and recovery | Understand effective settings, check prerequisites and authentication readiness, explain network access, explicitly probe connectivity, and recover from failed or interrupted operations. |
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
reported without exposing values. A `.env` file may supply `NO_PROXY` when proxy
bypass destinations are not explicitly configured in the profile; if both
sources define it, the CLI reports a conflict. Containment controls remain
restricted to their dedicated settings.

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
encrypted-storage policy.

Users can add custom CA certificates, individually or from a directory, when
required to trust the proxy or another configured endpoint. The CLI validates
the supplied certificate assets, rejects private-key material, and copies
accepted certificates into the managed profile directory. Custom CA trust is
also configurable without a proxy.

The review shows proxy configuration, bypass destinations, and added trust
certificates without exposing credentials. It explains that proxy bypass does
not bypass the egress policy, and adding a CA certificate extends which
certificate issuers the environment trusts.

Applying incorporates the configuration and certificates into the deployment.
Later changes to the original certificate files do not alter the managed copies;
replacing managed certificates requires another apply. Connectivity checks
distinguish proxy connection, authentication, and certificate-trust failures
where possible.

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

## Editing a profile

Users select an existing profile by name and edit the whole profile or a chosen
section, with existing non-secret values populated. Credential fields show
references and storage status rather than stored values. Before saving, they review the proposed
changes and correct validation errors without losing unrelated answers.
Cancellation preserves the previously saved profile and its managed assets.
Saving updates the desired configuration without applying a deployment or
altering running sessions, and explains how to preview and apply the changes.

## Listing and inspecting profiles

Users list profiles with their names, agents, selected deployments, and unapplied
changes. Empty lists provide next steps; invalid profiles do not prevent others
from appearing.

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
the cloned profile. Users supply a destination key, which may be the same as the
source key, or select the configured user-default key. Key scope is per-user or
per-profile, not per-credential. A source key may unlock multiple selected
credentials during the operation without repeated entry.

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

The CLI never deletes external bind-mount sources or offers to delete the
user-level encryption key. It removes the deleted profile key reference and
offers deletion of any exclusively owned, CLI-managed profile-level key material.
Shared or externally managed keys remain untouched. Whether the CLI manages key
material at all, rather than only referencing user-provided keys, remains a
decision for the detailed key-management specification.

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

Users opting into encrypted storage configure a user-level default encryption
key, with optional per-profile key overrides. Unlocking material stays outside
profile directories and exports. At launch, the CLI unlocks and supplies only
the credentials required by the selected agent; it never supplies the encryption
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

## Sharing and migration

Configuration-package export and import belong to the initial scope.

Users export a managed profile to share its configuration or transfer it to
another installation. The package contains `profile.toml` and eligible
profile-owned assets. It identifies external bind-mount dependencies without
copying their contents. Workspace contents, Docker volume contents, deployment
history, credentials (including encrypted credentials), and encryption keys are
excluded.

Users import a package to create an independently managed profile. Import
validates the package, resolves profile-name collisions, and identifies
dependencies requiring local configuration before deployment. Subsequent changes
to, or loss of, the package source do not affect the imported profile. External
runtime dependencies may still be required; importing configuration does not
make the environment self-contained.

Package format, asset eligibility, enforcement of credential exclusion, and
collision-resolution behavior remain to be specified. Native agent settings may contain credentials;
their presence in a profile directory does not make them safe to export.

## Deferred backup and restore

CLI-managed backup and restore are outside the initial scope. Their scope and
recovery guarantees require a later decision, including treatment of mutable
agent home directory contents, authentication state, Docker resources, and
consistency while sessions are active.

Users may copy profile directories with external filesystem tools. Such copies,
and configuration-package exports, do not constitute a CLI guarantee of complete
environment backup or restoration.
