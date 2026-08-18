---
icon: lucide/server
---

# Local models

This page is a test plan and a set of **candidate** configurations. It is not
an always-works guide. Agent CLIs, configuration schemas, authentication
ordering, and local-server compatibility change independently. Record the
exact agent version whenever a recipe is tested, and re-test after rebuilding
an image.

!!! warning "Testing status"

    All recipes on this page have not been verified yet. A configuration derived from upstream documentation is still only a candidate until its row is updated with observed results.

## Test record

Use this record for each agent and server combination:

| Field | Value |
|---|---|
| Status | Candidate / routing verified / generation verified |
| Agent image | Image name and digest or build date |
| Agent version | Exact output of the agent's `--version` command |
| Test date | `YYYY-MM-DD` |
| Server | llama.cpp, Ollama, vLLM, LM Studio, or other implementation and version |
| Protocol | Anthropic Messages, OpenAI Responses, or Chat Completions |
| Authentication mode | Keyless, placeholder key, or environment variable; never record a credential |
| Network path | General form such as LAN, host gateway, or private remote; do not record an address |
| Persistent state checked | Trust, session/history, provider selection, and restart behavior |
| Result/notes | Sanitized failure or successful behavior |

Do not upgrade a status from **candidate** based only on a model appearing in a
picker or `/models` response. “Routing verified” means the server received a
request from the container. “Generation verified” means the agent completed a
turn, including any required tool-call round trip.

## Scope and privacy

Test results should establish compatibility between an agent version, an API
protocol, and an inference-server implementation and version. They do not need
to identify the loaded model or disclose how a private network is addressed.
Once routing and generation work through a compatible API, the specific model
is primarily a local deployment choice, subject to having the capabilities the
agent requires.

The uppercase values in the candidate commands are placeholders to replace
privately when running a test. They are not fields to publish. Do not commit or
include any of the following in a test record:

- IP addresses, hostnames, ports, or details of private network topology;
- model names, model IDs, quantizations, or context-limit choices;
- credentials, tokens, or identifying environment-variable values; or
- unsanitized logs or errors containing any of the above.

The container still needs a route to the inference server and an egress rule
that permits that destination. Keep those values in the local invocation or
private configuration rather than the documentation.

## AdaL

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `adal --version` from the hardened invocation |
| Expected protocol | Ollama API |
| Shared state | `adal-home` persists AdaL credentials, provider selection, sessions, MCP authentication, skills, and plugins under `~/.adal` |
| Candidate mechanism | Start Ollama separately, allow only its reachable host, then select the local model in AdaL's `/model` dialog |

AdaL documents local-model support through Ollama. The image intentionally
does not install Ollama or a model: the inference service must be operated
separately. Make the service reachable from the container through a private
network path, then allow only that hostname or IP. Do not use `localhost` for
a model server on the Docker host; from the workload it refers to the AdaL
container itself.

Candidate invocation:

```sh
AGENT_ALLOWED_EGRESS=LOCAL_MODEL_HOST \
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e AGENT_ALLOWED_EGRESS \
  -v adal-home:/home/adal \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  adal
```

In AdaL, use `/model`, select the **Ollama** section, and choose the model
served by the reachable Ollama instance. AdaL documents local models as a
preview feature and notes that some capabilities, including image input, are
not available. Confirm that the local selection survives a restart without
replacing the volume-backed AdaL settings, and that the agent does not fall
back to a hosted route.

## Claude Code

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `contained_claude --version` |
| Expected protocol | Anthropic Messages-compatible endpoint |
| Shared state | `claude-home` remains mounted; project memory and other home state remain shared |
| Candidate mechanism | Runtime environment variables; do not shadow `settings.json` |

Candidate invocation:

```sh
CONTAINED_CLAUDE_EGRESS=LOCAL_MODEL_HOST \
contained_claude --docker \
  -e ANTHROPIC_BASE_URL=http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT \
  -e ANTHROPIC_AUTH_TOKEN=local-placeholder \
  -e ANTHROPIC_MODEL=LOCAL_MODEL_ID \
  --
```

The endpoint must implement the Anthropic API behavior Claude Code uses; a
Chat Completions-only server is not sufficient. Confirm whether the server
expects the base URL with or without `/v1`. See the upstream
[Claude Code environment-variable reference](https://code.claude.com/docs/en/env-vars).

## Codex

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `contained_codex --version` |
| Expected protocol | OpenAI Responses API |
| Shared state | `codex-home` remains mounted; trust, authentication, history, and sessions remain shared |
| Candidate mechanism | CLI configuration overrides plus an optional read-only model catalog |

Create `codex-models.json` using the schema accepted by the tested Codex
version. Then invoke Codex without replacing its mutable `config.toml`:

```sh
CONTAINED_CODEX_EGRESS=LOCAL_MODEL_HOST \
contained_codex --docker \
  -v "$PWD/codex-models.json:/home/codex/.codex/models.json:ro" \
  -- \
  --model "LOCAL_MODEL_ID" \
  --config 'model_provider="local_compatible"' \
  --config 'model_catalog_json="/home/codex/.codex/models.json"' \
  --config 'model_providers.local_compatible.name="Local compatible server"' \
  --config 'model_providers.local_compatible.base_url="http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT/v1"' \
  --config 'model_providers.local_compatible.wire_api="responses"' \
  --config 'model_providers.local_compatible.requires_openai_auth=false'
```

Test `/v1/responses`; a successful `/v1/models` or
`/v1/chat/completions` request is not enough. Codex's `/models` picker uses its
own catalog rather than discovering arbitrary models from the provider. Keep
the primary `config.toml` in the named volume because Codex may replace it
while recording project trust. See the upstream
[Codex advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced).

## Kilo Code

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `contained_kilo --version` |
| Expected protocol | Candidate uses OpenAI-compatible Chat Completions |
| Shared state | `kilo-home` remains mounted; global session and credential state remain available |
| Candidate mechanism | Separate read-only config selected with `KILO_CONFIG`; verify precedence and write behavior |

Candidate `kilo-local.json`:

```json
{
  "$schema": "https://app.kilo.ai/config.json",
  "model": "openai-compatible/local-model",
  "provider": {
    "openai-compatible": {
      "options": {
        "apiKey": "{env:LOCAL_MODEL_API_KEY}",
        "baseURL": "http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT/v1"
      },
      "models": {
        "local-model": {
          "id": "LOCAL_MODEL_ID",
          "name": "Local model",
          "tool_call": true,
          "limit": {
            "context": 32768,
            "output": 8192
          }
        }
      }
    }
  }
}
```

Candidate invocation:

```sh
LOCAL_MODEL_API_KEY=local-placeholder \
CONTAINED_KILO_EGRESS=LOCAL_MODEL_HOST \
contained_kilo --docker \
  -e LOCAL_MODEL_API_KEY \
  -e KILO_CONFIG=/etc/agent/kilo-local.json \
  -v "$PWD/kilo-local.json:/etc/agent/kilo-local.json:ro" \
  --
```

Replace the limits with the actual server limits. Verify that `KILO_CONFIG`
is loaded before any hosted-provider authentication and that Kilo does not try
to rewrite the selected file. See Kilo's upstream
[custom-model documentation](https://kilo.ai/docs/code-with-ai/agents/custom-models).

## OpenCode

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `contained_opencode --version` |
| Expected protocol | Candidate uses an OpenAI-compatible provider package |
| Shared state | `opencode-home` remains mounted; global credentials and XDG data remain shared |
| Candidate mechanism | Read-only project configuration layer; verify merge and persistence behavior |

Candidate `opencode.local.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "local-compatible/local-model",
  "providers": {
    "local-compatible": {
      "name": "Local compatible server",
      "package": "@opencode-ai/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT/v1"
      },
      "models": {
        "local-model": {
          "modelID": "LOCAL_MODEL_ID",
          "name": "Local model",
          "capabilities": {
            "tools": true,
            "input": ["text"],
            "output": ["text"]
          },
          "limit": {
            "context": 32768,
            "output": 8192
          }
        }
      }
    }
  }
}
```

Candidate invocation:

```sh
CONTAINED_OPENCODE_EGRESS=LOCAL_MODEL_HOST \
contained_opencode --docker \
  -v "$PWD/opencode.local.json:/workspace/$(basename "$PWD")/opencode.json:ro" \
  --
```

The provider intentionally omits an authentication environment variable for a
keyless endpoint. Verify that the project layer is accepted and does not
redirect unrelated future projects. See OpenCode's upstream
[provider documentation](https://opencode.ai/v2/docs/providers).

## Qwen Code

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `contained_qwen --version` |
| Expected protocol | OpenAI-compatible endpoint |
| Shared state | `qwen-home` remains mounted; settings, authentication, and MCP state remain shared |
| Candidate mechanism | Existing runtime environment-variable overrides |

The Qwen shortcut already forwards `OPENAI_API_KEY` and derives its base URL
and model from `CONTAINED_QWEN_BASE_URL` and `CONTAINED_QWEN_MODEL`:

```sh
OPENAI_API_KEY=local-placeholder \
CONTAINED_QWEN_EGRESS=LOCAL_MODEL_HOST \
CONTAINED_QWEN_BASE_URL=http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT/v1 \
CONTAINED_QWEN_MODEL=LOCAL_MODEL_ID \
contained_qwen
```

Some keyless servers still require a non-empty placeholder because the client
expects an API-key variable. Verify model selection rather than relying only
on a successful authentication screen. For multiple selectable local models,
test Qwen's `modelProviders` settings separately. See the upstream
[Qwen Code provider documentation](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/).

## Hermes

| Field | Value |
|---|---|
| Status | **Candidate** |
| Tested agent version | Not yet tested — record `contained_hermes --version` |
| Expected protocol | OpenAI-compatible `/v1/chat/completions` endpoint |
| Shared state | `hermes-data` remains mounted; config, auth, memories, sessions, and skills remain shared |
| Candidate mechanism | Let Hermes persist a named custom provider in its volume-backed `config.yaml` |

Candidate interactive setup:

```sh
CONTAINED_HERMES_EGRESS=LOCAL_MODEL_HOST contained_hermes model
```

Choose the custom/self-hosted endpoint and enter:

```text
Base URL: http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT/v1
API key: leave empty if the server permits it
Model: LOCAL_MODEL_ID
Context length: the server's effective context length
```

Hermes documents `config.yaml` as the source of truth and persists provider
switches to it, so do not bind-mount that individual file read-only. After a
named provider is stored, candidate switching syntax is:

```text
/model custom:local:LOCAL_MODEL_ID
```

Verify auxiliary models as well as the main turn: Hermes may route vision,
web extraction, approval classification, compression, or other auxiliary work
to a different provider unless configured otherwise. See the upstream
[Hermes provider documentation](https://github.com/hermes-agent-org/hermes/blob/main/website/docs/integrations/providers.md).

## Verification checklist

For every candidate, record evidence for all applicable items:

1. Capture the agent and server versions.
2. Start without hosted-provider credentials where the local route should be
   keyless.
3. Confirm the intended local server receives the request through the expected
   protocol; do not publish its address or the model identifier.
4. Complete one normal response and one tool-call round trip.
5. Accept or configure project trust, restart the container, and confirm that
   the decision persists without a configuration write error.
6. Start the same agent through its normal hosted-provider route and confirm
   that the persistent home state remains available.
7. Return to the local route and confirm that history/session behavior matches
   the agent's documented capabilities.
8. Confirm that egress permits the intended endpoint and still denies an
   unrelated destination.
9. Record any configuration migrations or files changed by the agent.
10. Re-test after upgrading the agent CLI or inference server.

When a candidate passes, update its status and tested-version field together;
never retain “routing verified” or “generation verified” without the version
and date that produced the result.
