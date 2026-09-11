---
name: litellm-provision-model
description: Add or update a provider-backed model on a running LiteLLM proxy in place, over the management API, given a provider name and an API key. Covers picking the litellm model string, testing the credential with /health/test_connection, writing it with /model/new or /model/{model_id}/update, verifying with a real chat completion, PATCHing input/output/cached-input rates when the deployed price map prices the model at zero, and optionally minting a virtual key with /key/generate. Use when the user supplies a provider plus an API key and wants it live on a LiteLLM proxy without editing config.yaml or restarting the container, or when spend logs show 0.0 for a working model.
disable-model-invocation: true
---

# Provision a provider model on a running LiteLLM proxy

Everything here happens over HTTP against a live proxy. No config file edits, no container restart. `POST /model/new` writes the deployment to Postgres and hot-reloads the router, so the model is callable seconds later

## Inputs

| Input | Required | Notes |
|---|---|---|
| `PROVIDER` | yes | e.g. `groq`, `anthropic`, `azure`, `bedrock` |
| `PROVIDER_API_KEY` | yes | secret, see [Handling the key](#handling-the-key) |
| `LITELLM_BASE_URL` | yes | defaults below |
| `LITELLM_MASTER_KEY` | yes | defaults below |
| `LITELLM_MODEL` | no | the `<provider>/<model>` string to route to, resolved in step 3 if absent |
| `MODEL_NAME` | no | public name clients call, defaults to `LITELLM_MODEL` |

Ask for anything missing except `LITELLM_MODEL` and `MODEL_NAME`. Never guess a master key

### Defaults for the agi-gateway-infra test server

This repo deploys LiteLLM from the upstream quickstart compose file, which already sets `STORE_MODEL_IN_DB: "True"`, so the DB-backed model management precondition is met out of the box

- `LITELLM_BASE_URL`: `http://litellm.test` if `/etc/hosts` maps it, otherwise `http://VM_IP:4000`
- `LITELLM_MASTER_KEY`: `sk-local-dev-master-key` (from `roles/litellm/files/docker-compose.override.yml`)
- Without a hosts entry and without the direct port, add `-H 'Host: litellm.test'` and hit `http://VM_IP`

Never change `LITELLM_SALT_KEY` after this runs. It encrypts stored provider keys, and rotating it makes every stored key undecryptable

## Handling the key

Put the key in a shell variable once, then build request bodies with `jq --arg` so it never appears literally in a later command:

```bash
export LITELLM_BASE_URL=http://litellm.test
export LITELLM_MASTER_KEY=sk-local-dev-master-key
export PROVIDER_API_KEY='<paste>'
```

Do not write the key into a file in the repo, a commit, a PR, or an issue. Do not echo it back. Scrub it from any command output you show the user

`/model/new` encrypts every `litellm_params` value with `LITELLM_SALT_KEY` before storing it, so the raw key is fine at rest on this test server. For production, prefer putting the key in the proxy's environment and passing `"api_key": "os.environ/<NAME>"` instead. That path needs a container recreate, which is not in place, so only take it when the user asks

## Workflow

Track progress with this checklist:

```
- [ ] 1. Resolve inputs
- [ ] 2. Confirm the proxy is reachable and the master key works
- [ ] 3. Pick the litellm model string
- [ ] 4. Test the credential before storing it
- [ ] 5. Create the model, or update the existing one
- [ ] 6. Verify with a real completion
- [ ] 7. Confirm spend is non-zero; PATCH rates if the proxy priced the model at zero
- [ ] 8. Optional: mint a virtual key
```

### Step 2: reachability and auth

```bash
curl -sS -o /dev/null -w 'liveliness %{http_code}\n' "$LITELLM_BASE_URL/health/liveliness"
curl -sS -o /dev/null -w 'model/info %{http_code}\n' \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info"
```

Expect `200` twice. A `401` on the second means the master key is wrong. Connection refused means the proxy is down, so stop and report rather than retrying blindly

In Cursor's agent sandbox, curl to `litellm.test` or the VM IP often returns HTTP 403 with body `Blocked by sandbox network policy`. That is not DNS or a wrong base URL. Re-run the curl with full network permissions (`required_permissions: ["all"]` on the Shell tool). `litellm.test` only resolves via `/etc/hosts` (public DNS has no record), so confirm the hosts entry exists before blaming resolution

### Step 3: pick the litellm model string

The format is `<provider>/<model>`. Treat your training knowledge as stale and look the model up, preferring the newest model in the family the user named:

```bash
curl -sS https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json \
  | jq -r 'keys[] | select(startswith("groq/"))'
```

If the litellm repo is checked out locally, grep `model_prices_and_context_window.json` there instead. If the user named an exact model, use it verbatim and only fall back to the lookup when it is missing from the map

Providers that need more than an api_key:

| Provider | Extra `litellm_params` |
|---|---|
| `azure` | `api_base`, `api_version`, and the model string is `azure/<deployment-name>` |
| `bedrock` | `aws_region_name` plus `aws_access_key_id` and `aws_secret_access_key` instead of `api_key` |
| `vertex_ai` | `vertex_project`, `vertex_location`, `vertex_credentials` |
| any OpenAI-compatible endpoint | `api_base`, with the model string as `openai/<model>` |

Ask for those extras rather than inventing them

### Step 4: test the credential before storing it

```bash
jq -n --arg model "$LITELLM_MODEL" --arg key "$PROVIDER_API_KEY" \
  '{mode:"chat", litellm_params:{model:$model, api_key:$key}}' \
| curl -sS -X POST "$LITELLM_BASE_URL/health/test_connection" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq '{status, error: .result.error}'
```

This returns HTTP 200 whether or not the credential works, so branch on `.status`. On `"error"`, report `.result.error` and stop. Do not store a credential that failed here

This endpoint rejects `os.environ/...` values supplied in the request body, so it can only probe raw credentials or ones already loaded on the proxy

### Step 5: create, or update if the name is taken

List what exists first:

```bash
curl -sS -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info" \
  | jq -r '.data[] | [.model_info.id, .model_name, .litellm_params.model] | @tsv'
```

`POST /model/new` with a `model_name` that already exists adds a second deployment to that group for load balancing instead of replacing it. That is almost never what the user wants when they are rotating a key

**New model:**

```bash
jq -n --arg name "$MODEL_NAME" --arg model "$LITELLM_MODEL" --arg key "$PROVIDER_API_KEY" \
  '{model_name:$name, litellm_params:{model:$model, api_key:$key}}' \
| curl -sS -X POST "$LITELLM_BASE_URL/model/new" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq
```

**Existing model, new credential:** PATCH the deployment by its `model_id` from the listing above:

```bash
jq -n --arg key "$PROVIDER_API_KEY" '{litellm_params:{api_key:$key}}' \
| curl -sS -X PATCH "$LITELLM_BASE_URL/model/$MODEL_ID/update" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @- \
| jq
```

`/model/new` swallows DB errors internally and surfaces them as a generic 500 `Failed to add model to db`. If you get that, the useful detail is in the proxy logs: `cd /opt/litellm && docker compose logs --tail 50 litellm` on the VM

### Step 6: verify

Confirm it registered, then spend real money on one token through the gateway:

```bash
curl -sS -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info" \
  | jq -r --arg n "$MODEL_NAME" '.data[] | select(.model_name == $n) | .model_info.id'

curl -sS -X POST "$LITELLM_BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":16}" \
  | jq '{model, content: .choices[0].message.content}'
```

A completion that comes back with content is the proof the provisioning worked. Show the user the command and the output

A working completion does **not** prove cost tracking works. The deployed proxy (LiteLLM 1.98.0 as of 2026-09) ships an older `model_prices_and_context_window.json` than GitHub `main`. A model that exists on `main` can still register here with `input_cost_per_token: 0`. Completions succeed, `x-litellm-response-cost` is `0.0`, and `/spend/logs` records `spend: 0.0` with no error. That is how `meta/muse-spark-1.3` and `meta/muse-spark-1.3-contributor` first landed

### Step 7: confirm spend, PATCH rates if zero

Read the rates the **running** proxy attached to the new row, not the GitHub map:

```bash
curl -sS -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/model/info" \
  | jq --arg n "$MODEL_NAME" '.data[] | select(.model_name == $n) | {
      id: .model_info.id,
      input: .model_info.input_cost_per_token,
      output: .model_info.output_cost_per_token,
      cache_read: .model_info.cache_read_input_token_cost
    }'
```

If `input` is `0` or missing, look the model up on the current map (or the provider's pricing page) and write the per-token rates onto the deployment. Costs are dollars per token, not per million:

```bash
# Example: rates LiteLLM main listed for meta/muse-spark-1.3-contributor
# (source: https://ai.developer.meta.com/docs/pricing-rate-limits)
#   input $0.10 / 1M  -> 1e-07
#   output $0.20 / 1M -> 2e-07
#   cached $0.002 / 1M -> 2e-09
# meta/muse-spark-1.3 was 1.25e-06 / 4.25e-06 / 1.5e-07
export MODEL_ID='<id from the listing above>'
jq -n --arg id "$MODEL_ID" \
  --argjson inc 1e-07 --argjson outc 2e-07 --argjson cachec 2e-09 \
  '{model_info:{
      id:$id,
      input_cost_per_token:$inc,
      output_cost_per_token:$outc,
      cache_read_input_token_cost:$cachec,
      supports_prompt_caching:true
    }}' \
| curl -sS -X PATCH "$LITELLM_BASE_URL/model/$MODEL_ID/update" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' --data @-
```

The PATCH writes into the same Postgres row as `/model/new`, so it survives container recreate. It is lost if someone deletes the model and re-adds it without the rates

Re-run the step 6 completion and check the cost headers (LiteLLM 1.98 also emits the split `*-input` / `*-output` fields; older scripts that only read `x-litellm-response-cost` can print `None` even when spend is set):

```bash
curl -sS -D - -o /tmp/completion.json \
  -X POST "$LITELLM_BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":16}" \
| grep -i 'x-litellm-response-cost'
```

Expect a non-zero `x-litellm-response-cost`. Hand-check: `(prompt - cached) * input + cached * cache_read + completion * output`. Then confirm the proxy persisted it:

```bash
curl -sS -H "Authorization: Bearer $LITELLM_MASTER_KEY" "$LITELLM_BASE_URL/spend/logs" \
  | jq --arg n "$MODEL_NAME" '[.[] | select(.model == $n)] | .[-3:] | .[] | {startTime, spend, prompt_tokens, completion_tokens}'
```

`/spend/logs` stores the discounted `spend` but has no cached-token column. The cache count only exists on the live response (`usage.prompt_tokens_details.cached_tokens`)

Do not invent rates. If the model is missing from both the deployed map and GitHub `main`, stop and ask for the provider's published per-million prices

### Step 8: optional virtual key

Only when the user asks for one. Scope it to the model just added:

```bash
curl -sS -X POST "$LITELLM_BASE_URL/key/generate" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"models\":[\"$MODEL_NAME\"],\"key_alias\":\"$MODEL_NAME-test\",\"max_budget\":5,\"duration\":\"30d\"}" \
  | jq '{key, expires}'
```

Then repeat the step 6 completion with that key in place of the master key. Hand the key to the user once and do not persist it anywhere

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
| 500 `Set 'STORE_MODEL_IN_DB='True'` | DB-backed model management is off. Add `STORE_MODEL_IN_DB: "True"` to the compose environment and recreate the container |
| 500 `No DB Connected` | The proxy is running without `DATABASE_URL`. The quickstart compose sets it, so check the Postgres service is healthy |
| 401 on management calls | Wrong master key, or you sent a virtual key that lacks admin rights |
| `/model/new` returns 200 but calls fail with a provider auth error | The stored key is bad, or `LITELLM_SALT_KEY` changed after it was stored, which corrupts decryption. Re-PATCH the credential |
| `LLM Provider NOT provided` on a completion | `litellm_params.model` is missing its provider prefix |
| Two rows share a `model_name` | A duplicate `/model/new`. Delete the stale `model_id` |
| Reaches nginx but 404s | Wrong Host header. Use `-H 'Host: litellm.test'` or hit port 4000 directly |
| 403 `Blocked by sandbox network policy` on curl | Agent sandbox blocked outbound HTTP to the VM or `litellm.test`. Re-run with full network permissions, not a different URL |
| Completions work but `spend` / `x-litellm-response-cost` is `0.0` | The running LiteLLM image's price map does not know this model (newer than the image, or a custom `api_base`). PATCH `model_info` rates as in step 7. Recheck `model/info` after, not the GitHub JSON |
| Cached tokens appear on the response but spend does not drop | `cache_read_input_token_cost` was never set, so LiteLLM bills cached tokens at the full input rate. PATCH that field and retry a warm prefix |
