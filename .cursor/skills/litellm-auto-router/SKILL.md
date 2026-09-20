---
name: litellm-auto-router
description: Create or retune a LiteLLM complexity auto router (auto_router/complexity_router) on a running proxy over the management API. Covers listing tier models, validating config, dry-run Test Routing, POST /model/new or PATCH /model/{id}/update, verifying with chat completions, and the UI Test Routing / Test Connection / Logs checklist. Use when the user asks to enable auto router, smart-router, change classifier_type or tiers, retune complexity_router_config, session_affinity, keyword rules, or experiment with auto-routing settings.
---

# Create or retune a LiteLLM auto router

Everything here happens over HTTP against a live proxy. No `config.yaml` edits, no container restart. The auto router is a DB-backed model whose `litellm_params.model` is `auto_router/complexity_router`. Clients call it by `model_name` (e.g. `smart-router`).

Docs: https://docs.litellm.ai/docs/proxy/auto_routing#ui

## Inputs

| Input | Required | Notes |
|---|---|---|
| `LITELLM_BASE_URL` | yes | defaults below |
| `LITELLM_MASTER_KEY` | yes | defaults below |
| `ROUTER_NAME` | yes for create | public name clients pass as `model`, e.g. `smart-router` |
| `TIERS` | yes for create | map of SIMPLE/MEDIUM/COMPLEX/REASONING → existing `model_name`s |
| `DEFAULT_MODEL` | yes for create | `complexity_router_default_model`; usually the MEDIUM or smartest tier |
| `CLASSIFIER_TYPE` | no | `heuristic` (default) or `llm` |
| `CLASSIFIER_LLM` | if `llm` | public `model_name` for the classifier |
| Other knobs | no | see [Experiment knobs](#experiment-knobs) |

Ask for anything missing on create. For retune, take only the fields the user wants changed and merge them into the full existing config (see [Update](#step-5-create-or-update)).

### Defaults for the agi-gateway-infra test server

Same as `litellm-provision-model`. `STORE_MODEL_IN_DB` is already on.

- `LITELLM_BASE_URL`: `http://litellm.test` if `/etc/hosts` maps it, otherwise `http://VM_IP:4000`
- `LITELLM_MASTER_KEY`: `sk-local-dev-master-key` (from `roles/litellm/files/docker-compose.override.yml`)
- Without a hosts entry and without the direct port, add `-H 'Host: litellm.test'` and hit `http://VM_IP`
- UI: http://litellm.test/ui — login `admin` / `sk-local-dev-master-key`

Never change `LITELLM_SALT_KEY`. Sandbox curl that returns 403 `Blocked by sandbox network policy` needs full network permissions (`required_permissions: ["all"]` on the Shell tool).

```bash
export LITELLM_BASE_URL=http://litellm.test
export LITELLM_MASTER_KEY=sk-local-dev-master-key
export ROUTER_NAME=smart-router
```

## Workflow

```
- [ ] 1. Resolve inputs
- [ ] 2. Reachability and auth
- [ ] 3. List models; resolve tier names from live model_name values
- [ ] 4. Validate config + dry-run Test Routing
- [ ] 5. Create or update
- [ ] 6. Verify with two real completions
- [ ] 7. Point the human at the UI checklist (do not create a second router in the UI)
```

### Step 2: reachability and auth

```bash
curl -sS -o /dev/null -w 'liveliness %{http_code}\n' "$LITELLM_BASE_URL/health/liveliness"
curl -sS -o /dev/null -w 'model/info %{http_code}\n' \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info"
```

Expect `200` twice. A `401` on the second means the master key is wrong.

### Step 3: list models; never invent tier targets

Tiers must name **existing public `model_name` values**, not invent aliases.

```bash
curl -sS -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info" \
  | jq -r '.data[] | [.model_info.id, .model_name, .litellm_params.model] | @tsv'
```

Note any existing row whose `litellm_params.model` is `auto_router/complexity_router` and whose `model_name` is `$ROUTER_NAME`. That is an update, not a create.

### Step 4: validate and dry-run Test Routing

Build `complexity_router_config` once (example first-enablement for this repo):

```bash
export FLASH=gemini/gemini-3.5-flash-lite
export MUSE=meta/muse-spark-1.3-contributor

CONFIG=$(jq -n --arg flash "$FLASH" --arg muse "$MUSE" '{
  tiers: {
    SIMPLE: $flash,
    MEDIUM: $muse,
    COMPLEX: $muse,
    REASONING: $muse
  },
  classifier_type: "heuristic",
  session_affinity: false
}')
```

Optional validate (saves nothing). Newer docs name `/auto_router/validate_complexity_router_config`; some images also try `/auto_router/validate_config`. **This repo's deployed quickstart image may 404 both** — that is fine; rely on `test_routing` instead.

```bash
jq -n --argjson cfg "$CONFIG" '{complexity_router_config: $cfg}' \
| curl -sS -w '\nhttp %{http_code}\n' -X POST "$LITELLM_BASE_URL/auto_router/validate_complexity_router_config" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @-
```

If you get `"valid": true`, continue. If `404`, skip. If `"valid": false`, fix `error` and stop.

Dry-run routing (classifies only; does not call the routed model; heuristic is free):

```bash
# Expect SIMPLE → flash
jq -n --argjson cfg "$CONFIG" --arg muse "$MUSE" --arg name "$ROUTER_NAME" '{
  prompt: "What is 2+2?",
  complexity_router_config: $cfg,
  default_model: $muse,
  router_name: $name
}' \
| curl -sS -X POST "$LITELLM_BASE_URL/auto_router/test_routing" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq '{routed_model, routed_model_configured, routing_decision}'

# Expect REASONING → muse (need two+ reasoning markers, e.g. "think through" + "step by step")
jq -n --argjson cfg "$CONFIG" --arg muse "$MUSE" --arg name "$ROUTER_NAME" '{
  prompt: "Please think through this carefully. Analyze step by step how we should refactor the authentication subsystem across microservices.",
  complexity_router_config: $cfg,
  default_model: $muse,
  router_name: $name
}' \
| curl -sS -X POST "$LITELLM_BASE_URL/auto_router/test_routing" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq '{routed_model, routed_model_configured, routing_decision}'
```

A short “think step by step about X” often stays SIMPLE — only one reasoning marker. Confirm `tier` / `routed_model` before writing.

An `llm` classifier or semantic keyword matching on Test Routing bills the classifier/embedding call to the calling key.

### Step 5: create or update

**Critical merge rule:** LiteLLM shallow-merges `litellm_params`. Sending only `{classifier_type: "llm"}` **replaces the entire** `complexity_router_config` and wipes tiers. Always GET the current row, merge into the full nested config, then PATCH the complete `complexity_router_config` (and `complexity_router_default_model` if that changed). Always keep `litellm_params.model: "auto_router/complexity_router"`.

**New router:**

```bash
jq -n --arg name "$ROUTER_NAME" --argjson cfg "$CONFIG" --arg muse "$MUSE" '{
  model_name: $name,
  litellm_params: {
    model: "auto_router/complexity_router",
    drop_params: true,
    complexity_router_config: $cfg,
    complexity_router_default_model: $muse
  }
}' \
| curl -sS -X POST "$LITELLM_BASE_URL/model/new" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq
```

**Existing auto router** (same `model_name`): PATCH by `model_id` from the listing. GET first, merge, then:

```bash
export MODEL_ID='<id of the auto_router/complexity_router row>'

# Example: switch classifier to llm while keeping tiers
CURRENT=$(curl -sS -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info" \
  | jq --arg id "$MODEL_ID" '.data[] | select(.model_info.id == $id)')

MERGED=$(jq -n --argjson row "$CURRENT" --arg clf "$CLASSIFIER_LLM" '
  ($row.litellm_params.complexity_router_config // {}) as $c
  | $c * {
      classifier_type: "llm",
      classifier_llm_config: {model: $clf, timeout_ms: 2000},
      classifier_fallback: "heuristic"
    }
')

jq -n --argjson cfg "$MERGED" --arg def "$(jq -r '.litellm_params.complexity_router_default_model // empty' <<<"$CURRENT")" '{
  litellm_params: {
    model: "auto_router/complexity_router",
    complexity_router_config: $cfg,
    complexity_router_default_model: $def
  }
}' \
| curl -sS -X PATCH "$LITELLM_BASE_URL/model/$MODEL_ID/update" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq
```

`POST /model/new` with a name that already exists adds a **second** deployment to that group. Never do that for an auto router. If a duplicate appears, delete the stale `model_id`.

### Step 6: verify with two real completions

```bash
curl -sS -D - -o /tmp/ar-simple.json \
  -X POST "$LITELLM_BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$ROUTER_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 2+2?\"}],\"max_tokens\":32}" \
| grep -iE 'HTTP/|x-litellm-model'

jq '{model, content: .choices[0].message.content}' /tmp/ar-simple.json

curl -sS -D - -o /tmp/ar-reason.json \
  -X POST "$LITELLM_BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$ROUTER_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"Please think through this carefully. Analyze step by step how we should refactor the authentication subsystem across microservices.\"}],\"max_tokens\":64}" \
| grep -iE 'HTTP/|x-litellm-model'

jq '{model, content: .choices[0].message.content}' /tmp/ar-reason.json
```

Body `model` stays `$ROUTER_NAME` unless `return_raw_model_name` is on. The served deployment is in `x-litellm-model-name` / `x-litellm-model-id` and on the Logs routing-decision card. Expect flash-lite on the short prompt and muse on the reasoning prompt. Muse may spend the whole `max_tokens` budget on `reasoning_tokens` and leave `content` null (`finish_reason: length`); that still proves routing if the headers name muse. Raise `max_tokens` or treat headers + Logs as the proof, then tell the human to run the [UI checklist](#manual-ui-test-after-create).

### Step 7: UI checklist for the human

Do **not** create a second router from **Add Model → Save**. Leave the [Manual UI test after create](#manual-ui-test-after-create) section for the human (or run it yourself with browser tools if asked).

## Experiment knobs

| Knob | Where | Notes |
|---|---|---|
| `tiers.SIMPLE` … `REASONING` | `complexity_router_config` | string or list of `model_name`s; all four required |
| `complexity_router_default_model` | `litellm_params` | when no ask can be extracted |
| `classifier_type` | config | `heuristic` or `llm` |
| `classifier_llm_config.model` | config | must be a live `model_name` |
| `classifier_llm_config.timeout_ms` | config | e.g. `2000` |
| `classifier_llm_config.system_prompt` | config | replaces built-in rubric; omit for default |
| `classifier_fallback` | config | `heuristic` (default) or `default_model` |
| `classifier_context_window_size` | config | LLM only; default `3`; `0` disables |
| `session_affinity` | config | default `false`; pin first-turn model when `true` |
| `keyword_tier_rules` | config | list of `{keywords, tier}` |
| `return_raw_model_name` | config | put resolved model in response `model` |
| `drop_params` | `litellm_params` | keep `true` when tiers span providers |
| `classifier_plugin` | config file only | **cannot** be set over API/UI |

More detail: [reference.md](reference.md).

## Manual UI test after create

Follows https://docs.litellm.ai/docs/proxy/auto_routing#ui. Login: http://litellm.test/ui — `admin` / `sk-local-dev-master-key`.

**Test Routing** classifies a prompt against the form config. It does not create a router and does not call the model it would pick. Same routing-decision card as Logs (`tier`, `cause`, routed model). Heuristic is free; LLM/semantic bills the classifier/embedding.

**Test Connection** sends a real minimal `/v1/chat/completions` (or embeddings) **per distinct tier model group**. Green = reachable; red = provider error. Shared groups collapse to one row.

Do **not** click **Save** on **Add Model** during this test. Saving would add a second deployment under the same `model_name`.

### 1. Confirm the saved row (edit modal, not Add Model)

1. **Models + Endpoints** → open `smart-router` (edit / model detail).
2. Expand **Detailed Configuration**.
3. Confirm against the intended payload (first enablement example):
   - Router name: `smart-router`
   - SIMPLE → `gemini/gemini-3.5-flash-lite`; MEDIUM/COMPLEX/REASONING → `meta/muse-spark-1.3-contributor`
   - Classifier: heuristic, **not** LLM Classifier
   - Semantic Keyword Matching: off; Adaptive: off
   - **Advanced > Session Affinity**: off
   - **Advanced > Compression**: not configured / None on both hops
   - **Return raw model name**: off

### 2. Test Connection

1. Click **Test Connection** on the edit form (or Add Model scratch pad filled to match — do not Save).
2. Expect **two** green rows when MEDIUM/COMPLEX/REASONING share muse: flash-lite and muse.
3. A red row is a credential/provider failure on that group — fix with `litellm-provision-model`, not by rewriting the router.

Never probe `auto_router/complexity_router` itself; probe **tier model groups**.

### 3. Test Routing

Prefer the edit modal when the button exists. If only on **Add Model > Auto Router tab**:

1. Choose **Custom Configuration** (not Configure automatically / Template).
2. Match the saved tiers + heuristic + Session Affinity off.
3. **Test Routing**. Do **not** Save.

Prompts:

- `What is 2+2?` → SIMPLE → flash-lite
- `Please think through this carefully. Analyze step by step how we should refactor the authentication subsystem across microservices.` → REASONING → muse (`cause` often `reasoning_override`)

Close without saving if you used Add Model as a scratch pad.

### 4. Logs drawer after live requests

1. **Logs** → open the two `smart-router` completions from step 6.
2. Each drawer’s routing-decision card should match Test Routing: tier, cause, served model.
3. Body `model` stays `smart-router` while Return raw model name is off.

Optional later: **Cost Optimization → Auto-router savings** once daily rollups exist. Skip on first enablement.

## Rollback

```bash
curl -sS -X POST "$LITELLM_BASE_URL/model/delete" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$MODEL_ID\"}"
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| 404 on `/auto_router/*` | Proxy image older than auto-router management endpoints; upgrade LiteLLM |
| 404 only on `/auto_router/validate_*` | Some images ship `test_routing` without validate; skip validate and use `test_routing` |
| Two rows share `smart-router` | Duplicate `/model/new`; delete the stale `model_id` |
| PATCH wiped tiers | Shallow merge of `complexity_router_config`; always PATCH the full nested object |
| 401 | Wrong master key |
| 403 sandbox | Re-run curl with full network permissions |
| Test Connection red | Broken tier model credentials; use `litellm-provision-model` |
| Body `model` is always the alias | Expected unless `return_raw_model_name: true` |
| `classifier_plugin` rejected | Config-file only; cannot set over HTTP |
