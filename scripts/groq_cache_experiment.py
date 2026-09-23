#!/usr/bin/env python3
"""Run prompt-cache experiments through a LiteLLM proxy.

Defaults to gemini/gemini-3.5-flash-lite. The other cheap model used for
tracking cache-token spend is meta/muse-spark-1.3-contributor. Gemini's
implicit cache needs a long prefix (~400 repeats, ~29k tokens); 40 is too
small and will report no cached_tokens.

Examples (from the repo root, against the test gateway):

  export LITELLM_BASE_URL=http://litellm.test
  export LITELLM_MASTER_KEY=sk-local-dev-master-key

  python3 scripts/groq_cache_experiment.py models

  python3 scripts/groq_cache_experiment.py cold-warm

  python3 scripts/groq_cache_experiment.py cold-warm \\
      --model meta/muse-spark-1.3-contributor

  python3 scripts/groq_cache_experiment.py switch

Each proxy run prints a LiteLLM session ID on its own line. Paste that
into Logs → Filters → Session ID to group the turns and see the session
total spend.

The direct mode skips the proxy and calls api.groq.com:

  export GROQ_API_KEY=...
  python3 scripts/groq_cache_experiment.py direct \\
      --model groq/openai/gpt-oss-20b
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

DEFAULT_BASE_URL = "http://litellm.test"
DEFAULT_MASTER_KEY = "sk-local-dev-master-key"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_QUESTION = "In one paragraph, explain why the static prefix must come first."
DEFAULT_MODEL_A = "gemini/gemini-3.5-flash-lite"
DEFAULT_MODEL_B = "meta/muse-spark-1.3-contributor"
DEFAULT_GROQ_MODEL = "groq/openai/gpt-oss-20b"

# Repeated so the static prefix is well above Gemini's implicit-cache floor.
_PREFIX_UNIT = (
    "Keep this block at the front of every request. Prompt caching only hits "
    "when the prefix matches exactly, so instructions, tool specs, and "
    "background stay here and the user question stays last. Cached input "
    "tokens are billed below the uncached input rate. This paragraph is "
    "padding so the prefix is long enough to be eligible for a cache hit. "
)


@dataclass
class Turn:
    label: str
    model: str
    prompt_tokens: int | None
    cached_tokens: int | None
    completion_tokens: int | None
    cost: str | None
    hit_pct: str
    content: str
    finish_reason: str | None
    usage: dict[str, Any]
    error: str | None = None


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("exp-%Y%m%d-%H%M%S")


def print_run_id(run_id: str) -> None:
    print("LiteLLM session ID (paste into Logs → Filters → Session ID):")
    print(run_id)


def system_prompt(repeats: int) -> str:
    return "".join(f"Block {i}. {_PREFIX_UNIT}" for i in range(repeats))


def request_json(
    url: str,
    *,
    method: str = "GET",
    key: str,
    body: dict[str, Any] | None = None,
    host_header: str | None,
    timeout: float,
) -> tuple[dict[str, str], Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    # Cloudflare in front of api.groq.com rejects the default Python-urllib agent with error 1010.
    req.add_header("User-Agent", "groq-cache-experiment/1.0")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if host_header:
        req.add_header("Host", host_header)
    context = ssl.create_default_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            raw_headers = {k.lower(): v for k, v in resp.headers.items()}
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"HTTP {exc.code} {url}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {url}: {exc.reason}") from exc
    return raw_headers, payload


def complete(
    *,
    base_url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
    tag: str,
    max_tokens: int,
    host_header: str | None,
    timeout: float,
    run_id: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "litellm_session_id": run_id,
        "metadata": {"tags": ["groq-cache-experiment", tag, f"run:{run_id}"]},
    }
    return request_json(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        method="POST",
        key=key,
        body=body,
        host_header=host_header,
        timeout=timeout,
    )


def complete_direct(
    *,
    groq_key: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    timeout: float,
) -> tuple[dict[str, str], dict[str, Any]]:
    body = {
        "model": model.removeprefix("groq/"),
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    return request_json(
        GROQ_API_URL,
        method="POST",
        key=groq_key,
        body=body,
        host_header=None,
        timeout=timeout,
    )


def parse_turn(label: str, model: str, headers: dict[str, str], payload: dict[str, Any]) -> Turn:
    usage = payload.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    prompt = usage.get("prompt_tokens")
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cache_read_input_tokens")
    completion = usage.get("completion_tokens")
    hit = "n/a"
    if isinstance(prompt, int) and isinstance(cached, int) and prompt > 0:
        hit = f"{100.0 * cached / prompt:.1f}%"
    choices = payload.get("choices") or []
    content = ""
    finish_reason = None
    if choices:
        content = ((choices[0].get("message") or {}).get("content")) or ""
        finish_reason = choices[0].get("finish_reason")
    return Turn(
        label=label,
        model=model,
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        cached_tokens=cached if isinstance(cached, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
        cost=headers.get("x-litellm-response-cost"),
        hit_pct=hit,
        content=content.replace("\n", " ").strip(),
        finish_reason=finish_reason,
        usage=usage if isinstance(usage, dict) else {},
    )


def print_turn(turn: Turn) -> None:
    print()
    print(f"=== {turn.label}  model={turn.model} ===")
    if turn.error:
        print(f"error: {turn.error}")
        return
    print(
        f"prompt_tokens={turn.prompt_tokens}  "
        f"cached_tokens={turn.cached_tokens}  "
        f"hit={turn.hit_pct}  "
        f"completion_tokens={turn.completion_tokens}  "
        f"finish_reason={turn.finish_reason}  "
        f"x-litellm-response-cost={turn.cost}"
    )
    print("usage.prompt_tokens_details =", json.dumps(turn.usage.get("prompt_tokens_details"), indent=2))
    print("usage =", json.dumps(turn.usage, indent=2))
    if turn.content:
        snippet = turn.content if len(turn.content) <= 240 else turn.content[:237] + "..."
        print("assistant:", snippet)
    else:
        reasoning = (turn.usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        print(
            f"assistant: <empty> (finish_reason={turn.finish_reason}, reasoning_tokens={reasoning}). "
            "Raise --max-tokens so the answer fits after reasoning."
        )


def print_summary(turns: list[Turn]) -> None:
    print()
    print("summary")
    print(f"{'label':<22} {'model':<36} {'prompt':>8} {'cached':>8} {'hit':>7} {'cost':>12}")
    for turn in turns:
        print(
            f"{turn.label:<22} {turn.model:<36} "
            f"{str(turn.prompt_tokens):>8} {str(turn.cached_tokens):>8} "
            f"{turn.hit_pct:>7} {str(turn.cost):>12}"
        )


def cmd_models(args: argparse.Namespace) -> None:
    _headers, payload = request_json(
        f"{args.base_url.rstrip('/')}/model/info",
        key=args.api_key,
        host_header=args.host_header,
        timeout=args.timeout,
    )
    rows = payload.get("data") or []
    if not rows:
        print("No models registered. Provision models first.")
        return
    print(f"{'model_name':<36} {'litellm_params.model'}")
    for row in rows:
        params = row.get("litellm_params") or {}
        print(f"{row.get('model_name', ''):<36} {params.get('model', '')}")


def cmd_cold_warm(args: argparse.Namespace) -> None:
    run_id = new_run_id()
    print_run_id(run_id)
    messages = [
        {"role": "system", "content": system_prompt(args.prefix_repeats)},
        {"role": "user", "content": args.question},
    ]
    turns: list[Turn] = []
    for label in ("cold", "warm"):
        headers, payload = complete(
            base_url=args.base_url,
            key=args.api_key,
            model=args.model,
            messages=messages,
            tag=f"cold-warm,{label}",
            max_tokens=args.max_tokens,
            host_header=args.host_header,
            timeout=args.timeout,
            run_id=run_id,
        )
        turn = parse_turn(label, args.model, headers, payload)
        print_turn(turn)
        turns.append(turn)
        if label == "cold" and args.pause > 0:
            time.sleep(args.pause)
    print_summary(turns)
    print()
    print_run_id(run_id)
    if turns[0].cached_tokens:
        print(
            "\nnote: cold already had cached_tokens > 0. "
            "A leftover prefix from a recent run is still warm."
        )
    elif turns[-1].cached_tokens in (None, 0):
        print(
            "\nnote: warm cached_tokens was 0. Either this provider does not report cached "
            "tokens, the prefix is below the provider's cache floor, or the two calls "
            "were too far apart."
        )


def cmd_direct(args: argparse.Namespace) -> None:
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise SystemExit(
            "Set GROQ_API_KEY first. This mode calls api.groq.com directly, so it needs the\n"
            "Groq provider key, not the LiteLLM master key:  export GROQ_API_KEY=..."
        )
    messages = [
        {"role": "system", "content": system_prompt(args.prefix_repeats)},
        {"role": "user", "content": args.question},
    ]
    turns: list[Turn] = []
    for label in ("direct-cold", "direct-warm"):
        headers, payload = complete_direct(
            groq_key=groq_key,
            model=args.model,
            messages=messages,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        turn = parse_turn(label, args.model, headers, payload)
        print_turn(turn)
        turns.append(turn)
        if label == "direct-cold" and args.pause > 0:
            time.sleep(args.pause)
    print_summary(turns)
    if any(turn.cached_tokens for turn in turns):
        print(
            "\nGroq reported cached tokens on this direct call. If the same prompt through the\n"
            "proxy reported none, LiteLLM is dropping the field, not Groq."
        )
    else:
        print(
            "\nGroq reported no cached tokens even without the proxy in the path, so the gap is\n"
            "upstream of LiteLLM. Check that this model and account support prompt caching."
        )
    print(
        "note: both paths share one Groq account and cache the same prefix, so a proxy run in\n"
        "the last couple of hours can leave direct-cold already warm. That still counts as proof\n"
        "that Groq is caching."
    )


def cmd_switch(args: argparse.Namespace) -> None:
    run_id = new_run_id()
    print_run_id(run_id)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt(args.prefix_repeats)}]
    script = [
        ("A-cold", args.model_a, "What is prompt caching, and why does prefix order matter?"),
        ("A-warm", args.model_a, "Give one concrete example of a cache hit versus a cache miss."),
        ("B-after-A", args.model_b, "How does switching models mid-conversation affect the cache?"),
        ("B-warm", args.model_b, "What would break a cache hit after this model swap?"),
        ("A-after-B", args.model_a, "Summarize this conversation in two sentences."),
    ]
    turns: list[Turn] = []
    for label, model, question in script:
        messages.append({"role": "user", "content": question})
        headers, payload = complete(
            base_url=args.base_url,
            key=args.api_key,
            model=model,
            messages=messages,
            tag=f"switch,{label}",
            max_tokens=args.max_tokens,
            host_header=args.host_header,
            timeout=args.timeout,
            run_id=run_id,
        )
        turn = parse_turn(label, model, headers, payload)
        print_turn(turn)
        turns.append(turn)
        messages.append({"role": "assistant", "content": turn.content or ""})
        if args.pause > 0:
            time.sleep(args.pause)
    print_summary(turns)
    print()
    print_run_id(run_id)
    print(
        "\nwhat to look for: A-cold and B-after-A should be near cached_tokens=0 "
        "(new model, or first use of this prefix). A-warm and B-warm should rise. "
        "A-after-B may still show a partial hit on the shared system+early-A prefix "
        "if that prefix is still in the provider's cache."
    )


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--base-url", default=_env("LITELLM_BASE_URL", DEFAULT_BASE_URL))
    shared.add_argument("--api-key", default=_env("LITELLM_MASTER_KEY", DEFAULT_MASTER_KEY))
    shared.add_argument(
        "--host-header",
        default=_env("LITELLM_HOST_HEADER", ""),
        help="Set when calling the VM IP instead of litellm.test, e.g. litellm.test",
    )
    shared.add_argument("--timeout", type=float, default=120.0)
    shared.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Must cover reasoning tokens plus the answer; some models spend the budget on reasoning first",
    )
    shared.add_argument(
        "--prefix-repeats",
        type=int,
        default=400,
        help="How many times to repeat the static prefix block. Gemini needs ~400; 40 is below its cache floor",
    )
    shared.add_argument("--pause", type=float, default=3.0, help="Seconds to wait between turns")

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[shared],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    models = sub.add_parser("models", parents=[shared], help="List models registered on the proxy")
    models.set_defaults(func=cmd_models)

    cold = sub.add_parser("cold-warm", parents=[shared], help="Send the same prompt twice on one model")
    cold.add_argument("--model", default=_env("LITELLM_MODEL", DEFAULT_MODEL_A))
    cold.add_argument("--question", default=DEFAULT_QUESTION)
    cold.set_defaults(func=cmd_cold_warm)

    direct = sub.add_parser(
        "direct",
        parents=[shared],
        help="Same cold/warm pair sent straight to api.groq.com, bypassing the proxy",
    )
    direct.add_argument("--model", default=_env("LITELLM_MODEL", DEFAULT_GROQ_MODEL))
    direct.add_argument("--question", default=DEFAULT_QUESTION)
    direct.set_defaults(func=cmd_direct)

    switch = sub.add_parser("switch", parents=[shared], help="Multi-turn conversation that swaps model A and model B")
    switch.add_argument("--model-a", default=_env("LITELLM_MODEL_A", DEFAULT_MODEL_A))
    switch.add_argument("--model-b", default=_env("LITELLM_MODEL_B", DEFAULT_MODEL_B))
    switch.set_defaults(func=cmd_switch)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.host_header:
        args.host_header = None
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
