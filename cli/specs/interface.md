# CLI interface requirements

This document records agreed interface requirements as the user journeys are
developed. It is incomplete and does not describe the current implementation as
the required interface. Exact command syntax and unresolved choices below remain
subject to review and approval.

## Profile descriptions

Profiles support an optional user-provided description, editable during creation
and editing and displayed in profile and session inspection.

## Agent authentication setup

The interface distinguishes agent-managed authentication or setup at launch from
provider endpoint and credential configuration through the onboarding CLI.
Choices and remaining first-launch steps are agent-specific. Agent-managed setup
requires no endpoint or credential values in the profile; launch must not reject
this choice for missing CLI-supplied credentials. Existing authentication in a
reused agent home directory may avoid another login.

## Software selection

Package selection covers system packages, npm packages, isolated Python CLI
tools, and importable Python libraries. Each interactive category prompt must
show the image-provided optional defaults as a list at the time input is
requested, including an explicit indication if the list is empty. Showing the
defaults only in a later summary is insufficient.

Each category offers four explicit choices:

| Choice | Meaning |
|---|---|
| Keep defaults | Retain the image-provided optional package list. |
| Extend defaults | Retain the defaults and add user-selected packages. |
| Replace defaults | Replace the optional default list with the user-supplied list. |
| Set to none | Select no optional packages for this category. |

With no custom selection, the category keeps its defaults. Required infrastructure
packages remain separate and are not removed by any choice. Before saving,
review shows the selected mode and effective list for each category, distinguishing
defaults from customisations and identifying changes requiring an image rebuild.

Noninteractive inputs must express the same four modes and any associated
package lists unambiguously. Exact syntax and handling of duplicate or conflicting
package specifications remain to be specified.

Applying installs selected software into the image without silently expanding
runtime network access or removing home-installed tools. Diagnostics identify
home-installed tools that take precedence over image-installed versions.

## Agent home directory persistence

The default is per-profile persistence in a named Docker volume. The interface
also offers per-project persistence, an ephemeral agent home directory per
session, and explicit reuse of an existing Docker volume. These choices must
be expressible in noninteractive use; omission uses the per-profile default.

Review explains persistence and sharing of state, including authentication and
installed tools, and the possible need to authenticate again with a fresh or
ephemeral agent home directory. Different project paths must remain distinct
even when their directory names match. Changing persistence mode must not
silently copy, migrate, or delete existing data.

Exact option names, project identity rules, Docker volume naming, and ephemeral
storage lifecycle details remain to be specified.

## Additional bind mounts

Each additional bind mount specifies a host file or directory source, container
destination, and access mode. Read-only access is the default; writable access
requires an explicit choice. Noninteractive inputs must support these same
selections without prompting.

Review identifies exposed locations, explains that writable mounts can change
original host content, and distinguishes these mounts from the launch-time
workspace and Docker-managed agent home directory.

Apply and launch check source existence and expected type. Destination conflicts,
including overlaps with CLI-managed mounts, produce actionable errors. Missing
sources must never be silently created. Exact option syntax, path-resolution
rules, and destination-conflict rules remain to be specified.

## Runtime environment inputs

Users can specify literal non-secret environment values, host environment-variable
references, encrypted credential references, and an external `.env` file. Only
explicitly configured variables and those required by supported integrations are
passed. Review identifies sources without exposing credential values.

The profile records the `.env` location only. Apply checks accessibility and
structural validity; launch reads current contents without requiring an image
rebuild. The file is parsed as data, not executed. Its values must not appear in
output, managed profile assets, images, or exports. Export identifies the file
as an external dependency. Missing files and invalid entries are handled errors.

Whichever single configured source defines a given variable name is used. Two
or more configured sources defining the same name — including `HTTP_PROXY`,
`HTTPS_PROXY`, and `NO_PROXY` — must always be reported as a conflict,
regardless of which kinds of source they are.

Noninteractive inputs must express the same source selections without prompts.
Exact syntax, supported `.env` grammar, file-path resolution, duplicate handling,
and the full list of CLI-controlled variables remain to be specified.

## Passphrase and key-cache interface

The CLI always derives the encryption key ephemerally from the passphrase via
a KDF, and never stores or exports the passphrase or the derived key itself;
see [security.md](security.md#encryption-key-scope). The interface must
support:

- Interactive passphrase entry with no terminal echo, prompted whenever an
  operation needs to derive the key (creating or unlocking encrypted
  credential storage, rotation, export of a profile with encrypted
  credentials).
- Noninteractive passphrase supply via an explicit reference (e.g. a host
  environment variable), never as a literal command-line argument or stored
  in a profile file. A passphrase reference is distinct from a credential
  reference — it unlocks credential references, it is not one.
- An explicit, per-profile, off-by-default opt-in to caching the passphrase
  in the host's OS-managed credential store, offered separately from opting
  into encrypted credential storage itself. Caching is unavailable without an
  unlockable host session and must be reported as unavailable, not silently
  skipped, in noninteractive or CI contexts.
- Explicit per-profile disabling of caching, which clears any existing cache
  entry for that profile.

Review and diagnostics indicate whether a profile has an active passphrase
cache without displaying the passphrase. Noninteractive inputs must express
passphrase-reference and cache-opt-in choices unambiguously. Exact syntax
remains to be specified.

## Noninteractive operation

Noninteractive operation must not prompt. It does not implicitly approve
consequential choices. Required choices and confirmations must be expressible
explicitly through the interface. Where required input is absent, the CLI must
report the unresolved choice and how to supply it rather than wait for input or
silently approve it.

The following contracts derive from the approved journeys:

| Operation | Noninteractive interface requirement |
|---|---|
| Apply | Provide explicit confirmation options in place of interactive confirmation. Check Docker and required inputs and refresh the preview before changes. Without the required confirmation, do not perform the proposed changes. Applying does not launch an agent or stop existing sessions. |
| Rollback | Support selection of a retained deployment and explicit confirmation before changing the selected deployment. Check Docker and required resources and preview the effects on future launches. Missing resources leave the current selection unchanged. |
| Clone | Require explicit retain-or-skip selections for credential references and encrypted credentials, and the necessary source and destination passphrases to decrypt and re-encrypt retained encrypted credentials. Unresolved choices fail with actionable instructions. Destination key scope is strictly per-profile, not per-credential. |
| Remove | Express profile-removal confirmation and optional image and volume deletion choices explicitly. Removal automatically clears any cached passphrase for the profile; if the credential store cannot be inspected, report cache deletion as unavailable rather than skipping it silently. Resource protection rules still apply; noninteractive operation does not bypass them. |
| Preview | Inspect Docker automatically. If Docker is unavailable, do not claim deployment readiness. The noninteractive response to the offer of a limited metadata-only preview remains to be decided. |
| List and inspect | Remain available without Docker and identify unavailable or unchecked information. Credential references and storage status may appear; values must not. |

The credential policies in [security.md](security.md) apply equally to interactive
and noninteractive operation. Missing keys or failed decryption must not cause
plaintext storage as a fallback.

## Confirmation and selection

Noninteractive mode disables prompts but grants no approval. Applying requires
explicit approval of the proposed deployment changes. Profile removal and
optional resource deletions require their own explicit selections; a general
confirmation must not silently select additional resources for deletion. Missing
required choices cause an actionable error before the affected changes begin.

## Deployment history and rollback interface

History displays retained deployments with creation times, image identities,
change summaries, and the current selection. Users can choose a retained
deployment for rollback, including a convenient choice of the immediately
previous deployment.

Before changing selection, rollback checks Docker and required resources,
previews the effects on future launches, and requires confirmation. Noninteractive
use must express confirmation without prompting. The interface must explain that
rollback restores the image and recorded launch configuration, not the desired
profile, agent home directory contents, workspace contents, or running sessions.
Differences between the desired profile and restored deployment remain visible.
Missing required resources produce an explanation and preserve the current
selection. Exact target-selection and confirmation syntax remain to be specified.

## Launch interface

Users can launch the deployment selected for a named profile directly through the CLI
or through a generated shell shortcut, with consistent behavior. The invocation
directory becomes the workspace. Agent arguments apply to that invocation
without modifying the profile. Exact argument-forwarding syntax remains to be
specified.

Launch checks Docker, deployment resources, required bind-mount sources, and
credential availability, and identifies the deployment, workspace, and agent
home directory persistence and sharing scope. Unapplied changes are reported
without automatically applying them. A missing deployment produces instructions
for applying the profile first.

The agent remains interactive and attached to the terminal; terminal input,
signals, and the session exit status must be preserved. Routine launch has no
additional confirmation prompt. Missing prerequisites produce actionable errors.

## Session interface

Selecting a session displays information by default and does not modify or
terminate it. Inspection shows the agent, profile name and optional description,
deployment, workspace, container identity, start time, elapsed runtime, and
current Docker-reported state. Docker state must not be presented as proof of
agent responsiveness. Unavailable Docker must not appear as an empty session
list.

Normal exit takes place through the agent in its attached terminal. Session
management provides a separate, explicit force-termination action for an
unresponsive or otherwise unrecoverable session. Before proceeding, the CLI
identifies the exact container and warns about loss of unsaved work or
interruption of writes. Force termination does not delete the profile,
deployment, workspace, or persistent agent home directory.

Exact session selection and force-termination syntax, including noninteractive
target selection and confirmation, remain to be specified under the general
confirmation contract.

## Diagnostics interface

Diagnostics for a named profile report what was checked, the result, and a
suggested next action. Findings cover Docker availability, configuration,
deployment resources, bind mounts, credential availability, and integrations.
Results distinguish failures, warnings, and checks not performed. Credential
absence must not be presented as provider rejection of authentication.

Relevant Docker resources are inspected automatically without modification.
Checks that start temporary containers or contact external endpoints require
explicit selection in both interactive and noninteractive use. Noninteractive
mode must not implicitly select these checks. Network checks use the relevant
container environment and must not relax its restrictions to make a check pass.
Diagnosis reports recovery actions without automatically performing repairs.

Exact check-selection options and structured diagnostic output remain to be
specified.

## Update interface

Update checks accept a named profile and distinguish updates to the onboarding
CLI, image recipes, and image-installed agents or tools. Results explicitly
identify cases where update availability cannot be determined. Checking does
not change the profile or deployment.

Users select deployment updates and review and approve their effects through
the deployment preview and apply workflow. Noninteractive use requires explicit
update selections and approval under the existing confirmation contract. Updating
the onboarding CLI is a separate action.

Successful deployment updates retain the previous deployment for rollback and
affect subsequent launches. They do not stop existing sessions or automatically
replace tools installed in the persistent agent home directory.

Exact update-check and selection syntax, update sources, and how available
versions are determined remain to be specified.

## Cleanup interface

Standalone cleanup presents unused CLI-managed Docker resources for inspection
and explicit selection of eligible images or named volumes. Before deletion,
the preview identifies exact resources, known associations, and any
persistent-data loss. Docker inspection and explicit confirmation are required.
Noninteractive use must express resource selections and confirmation without
prompting; the same protection rules apply.

Resources referenced by containers, profiles, or retained deployments are
protected from deletion. Retirement of a retained deployment is an explicit
choice required before its otherwise-unused image becomes eligible. The
currently selected deployment cannot be retired.

Cleanup never deletes external bind-mount sources, workspaces, or encryption
keys. Partial failures identify deleted and remaining resources and explain
the failures. Exact resource-selection, deployment-retirement, and confirmation
syntax remain to be specified.

## Network, proxy, and certificate configuration

The interface presents proposed network destinations with their purposes and
allows users to accept or revise them. Additional development destinations are
explicit choices. Selecting packages must not silently grant runtime access.
Review identifies enforcement location, application destinations, gateway
bootstrap access, and the containment effects of broader access choices. It
distinguishes configured access from connectivity actually checked.

Users can configure HTTP(S) proxy addresses, bypass destinations, and credential
references or optional encrypted proxy credentials. SOCKS proxy support is
deferred to a future version. Custom CA certificates may be supplied individually
or from a directory, with or without a proxy. Accepted certificates are any
parseable X.509 certificate, including a single self-signed leaf certificate for
a specific endpoint, not only certificates marked as certificate authorities;
private-key material is rejected. Expired certificates or weak signature
algorithms are flagged as warnings and do not block acceptance on their own.

Applying incorporates accepted certificates into the container's system trust
store at image build time; changing certificates requires a rebuild.
Environment-variable trust hints (e.g. `NODE_EXTRA_CA_CERTS`) are a supplementary
layer only, never the sole mechanism for trust.

Review displays proxy configuration, bypass destinations, and added certificates
without credential values. It explains that proxy bypass does not bypass egress
restrictions, and distinguishes trust extended to an issuer from trust extended
to a single certificate. Changes to original certificate files do not update
managed copies; replacing managed certificates requires apply.

Connectivity checks for the configured proxy and certificates are a separate,
explicitly selected action under the diagnostics interface, not an implicit
part of review. They require the relevant network to be reachable at check time
and are unavailable otherwise; unavailability is reported, not treated as a
connection failure. Where run, they distinguish proxy connection, authentication,
and certificate-trust failures where possible.

Noninteractive inputs must support the same explicit network choices, proxy
settings, credential sources, and certificate assets. Exact syntax remains to
be specified.

## Gateway configuration interface

Users can choose local workload filtering or an existing supported gateway.
Gateway inputs include connection details, authentication references, trusted
host identity, and bootstrap destinations. These inputs must also be expressible
in noninteractive use; exact syntax remains to be specified.

Review distinguishes gateway bootstrap access from routed application traffic
and identifies the policy controlled by the profile versus policy managed at
the gateway. Missing or conflicting settings are reported before applying.
Explicit connectivity checks distinguish gateway connection failures from
failures reaching destinations through it. Gateway failure must not silently
fall back to unrestricted or direct application access.

This interface configures use of an existing gateway; it does not provision or
administer the gateway. Supported gateway details and validation rules remain
to be specified.

## Error handling

All CLI operations must handle errors and present clear user-facing messages
instead of terminating with an unhandled exception or raw traceback. This
requirement covers user-specified input errors, configuration and state errors,
filesystem and permission failures, Docker and subprocess failures, credential
and encryption failures, and unexpected internal exceptions. It applies to
interactive and noninteractive use.

Messages must identify the failed operation, explain the cause when known, and
provide a corrective or recovery action where possible. When the cause is
unknown, the CLI must say so rather than invent an explanation. Messages must
not expose credential values, encryption keys, or sensitive input through
exception text or subprocess output.

If an error occurs after changes have begun, the CLI must report known completed
actions, remaining work, and any uncertain state without claiming success or
rollback that has not occurred. Handled command failures must produce a nonzero
exit status; exact exit codes and machine-readable error formatting remain to
be specified.

## Decisions still required

- Exact spelling and placement of the noninteractive and confirmation options.
- How approval relates to a refreshed deployment preview and any changed inputs.
- Syntax for per-credential cloning choices, including passphrase supply for
  source decryption and destination re-encryption.
- Syntax for optional resource deletion and its confirmation.
- Noninteractive handling of unavailable Docker during preview.
- Complete noninteractive inputs for creation, editing, import, and export,
  including collision handling.
- Exit statuses and machine-readable output contracts.

These open decisions do not authorize implementation or establish unreviewed
defaults.
