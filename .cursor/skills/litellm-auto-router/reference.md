# Auto router knobs (reference)

Companion to [SKILL.md](SKILL.md). Full upstream docs: https://docs.litellm.ai/docs/proxy/auto_routing

## Pseudo-model

`litellm_params.model` must stay `auto_router/complexity_router`. That string is the discriminator; mangling it drops the deployment under `ignore_invalid_deployments`.

## Classification

Four ways to pick a tier. Keyword rules short-circuit first. Then the configured classifier runs. On classifier failure, `classifier_fallback` is `heuristic` (default) or `default_model`.

### Heuristic scorer (default)

Zero API calls. Dimensions: tokenCount, codePresence, reasoningMarkers, technicalTerms, simpleIndicators, multiStepPatterns, questionComplexity. Two or more reasoning markers force `REASONING` regardless of the weighted score.

Optional tuning: `tier_boundaries`, `token_thresholds`, `dimension_weights`, `custom_technical_keywords`.

### LLM classifier

```yaml
classifier_type: llm
classifier_llm_config:
  model: <public model_name>
  timeout_ms: 2000
  # system_prompt: <replaces built-in rubric>
classifier_fallback: heuristic   # or default_model
classifier_context_window_size: 3
classifier_context_per_turn_chars: 200
classifier_context_include_assistant_turns: false
```

Context-window keys apply only when `classifier_type` is `llm`. Values left at defaults may be omitted from the saved config.

### Keyword rules

```yaml
keyword_tier_rules:
  - keywords: ["hi", "hello", "thanks"]
    tier: SIMPLE
  - keywords: ["kubernetes", "k8s"]
    tier: REASONING
semantic_keyword_matching: false   # true needs embedding_model + non-empty rules
```

When multiple rules match, the router escalates to the highest tier (`SIMPLE < MEDIUM < COMPLEX < REASONING`).

### Custom classifier plugin

`classifier_type: custom` + `classifier_plugin: dotted.path` is **config.yaml only**. Not settable over the model-management API or UI.

## What gets classified

The router scores the last real human ask (reminder blocks stripped) plus, for some heuristic dimensions and the LLM classifier, the latest system prompt. Harness-only turns with no ask go to `complexity_router_default_model`.

## Tier pools

- String: pin one `model_name`
- List: uniform random pick (or Thompson sample if `adaptive: true`)
- Empty pools fail at config load

## Session affinity

`session_affinity: false` by default (every turn reclassified). Set `true` to pin the first-turn model for `session_affinity_ttl_seconds` (default 3600), keyed by `session_id` in request metadata. UI create/edit write the value explicitly.

This is separate from Router `optional_pre_call_checks` deployment affinity.

## Return raw model name

Default off: response body `model` stays the router alias. Set `return_raw_model_name: true` (UI: **Return raw model name**) to leave the resolved model in the body. Otherwise read `x-litellm-model-id` or the Logs routing-decision card.

## Alias litellm_params

`drop_params`, `cache_control_injection_points`, and other params on the router entry merge into the outbound tier call. Prefer `drop_params: true` when tiers span providers with different parameter sets.

## Decision log / UI card

Every decision emits `cause=` (e.g. `complexity_scorer`, `llm_classifier`, `literal_keyword_match`, `session_affinity_pin`). The Logs drawer and Test Routing show the same card: tier, cause, routed model.

## Management endpoints

| Method | Path | Role |
|---|---|---|
| POST | `/auto_router/validate_complexity_router_config` | Dry-run write gate |
| POST | `/auto_router/test_routing` | Classify one prompt without calling the routed model |
| POST | `/model/new` | Create router deployment |
| PATCH | `/model/{id}/update` | Retune (shallow-merge `litellm_params` — send full `complexity_router_config`) |
| POST | `/model/delete` | Rollback |

There is no separate `/auto_router/new`.
