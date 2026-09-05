#!/usr/bin/env python3
"""Run Groq prompt-cache experiments through a LiteLLM proxy.

Groq prompt caching is automatic and currently billed on the gpt-oss family.
This script never streams, because LiteLLM has dropped Groq cached_tokens on
streamed responses.

Examples (from the repo root, against the test gateway):

  export LITELLM_BASE_URL=http://litellm.test
  export LITELLM_MASTER_KEY=sk-local-dev-master-key

  python3 scripts/groq_cache_experiment.py models

  python3 scripts/groq_cache_experiment.py cold-warm \\
      --model groq/openai/gpt-oss-20b

  python3 scripts/groq_cache_experiment.py switch \\
      --model-a groq/openai/gpt-oss-20b \\
      --model-b groq/openai/gpt-oss-120b

Override the public LiteLLM model_name if you registered an alias.
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
from typing import Any

DEFAULT_BASE_URL = "http://litellm.test"
DEFAULT_MASTER_KEY = "sk-local-dev-master-key"
DEFAULT_MODEL_A = "groq/openai/gpt-oss-20b"
DEFAULT_MODEL_B = "groq/openai/gpt-oss-120b"

# Repeated so the static prefix is well above typical cache floors (~1k tokens).
_PREFIX_UNIT = (
    "Keep this block at the front of every request. Prompt caching on Groq "
    "only hits when the prefix matches exactly, so instructions, tool specs, "
    "and background stay here and the user question stays last. Cached input "
    "tokens are billed at half the uncached input rate. This paragraph is "
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
    usage: dict[str, Any]
    error: str | None = None


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


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
) -> tuple[dict[str, str], dict[str, Any]]:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "metadata": {"tags": ["groq-cache-experiment", tag]},
    }
    return request_json(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        method="POST",
        key=key,
        body=body,
        host_header=host_header,
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
    if choices:
        content = ((choices[0].get("message") or {}).get("content")) or ""
    return Turn(
        label=label,
        model=model,
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        cached_tokens=cached if isinstance(cached, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
        cost=headers.get("x-litellm-response-cost"),
        hit_pct=hit,
        content=content.replace("\n", " ").strip(),
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
        f"x-litellm-response-cost={turn.cost}"
    )
    print("usage.prompt_tokens_details =", json.dumps(turn.usage.get("prompt_tokens_details"), indent=2))
    print("usage =", json.dumps(turn.usage, indent=2))
    if turn.content:
        snippet = turn.content if len(turn.content) <= 240 else turn.content[:237] + "..."
        print("assistant:", snippet)


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
        print("No models registered. Provision Groq models first.")
        return
    print(f"{'model_name':<36} {'litellm_params.model'}")
    for row in rows:
        params = row.get("litellm_params") or {}
        print(f"{row.get('model_name', ''):<36} {params.get('model', '')}")


def cmd_cold_warm(args: argparse.Namespace) -> None:
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
        )
        turn = parse_turn(label, args.model, headers, payload)
        print_turn(turn)
        turns.append(turn)
        if label == "cold" and args.pause > 0:
            time.sleep(args.pause)
    print_summary(turns)
    if turns[0].cached_tokens:
        print(
            "\nnote: cold already had cached_tokens > 0. "
            "A leftover prefix from a recent run is still warm (Groq TTL is 2 hours)."
        )
    elif turns[-1].cached_tokens in (None, 0):
        print(
            "\nnote: warm cached_tokens was 0. Check that this model is in Groq's "
            "prompt-cache list (gpt-oss-20b / gpt-oss-120b / gpt-oss-safeguard-20b), "
            "that the prefix is long enough, and that you did not stream."
        )


def cmd_switch(args: argparse.Namespace) -> None:
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
        )
        turn = parse_turn(label, model, headers, payload)
        print_turn(turn)
        turns.append(turn)
        messages.append({"role": "assistant", "content": turn.content or ""})
        if args.pause > 0:
            time.sleep(args.pause)
    print_summary(turns)
    print(
        "\nwhat to look for: A-cold and B-after-A should be near cached_tokens=0 "
        "(new model, or first use of this prefix). A-warm and B-warm should rise. "
        "A-after-B may still show a partial hit on the shared system+early-A prefix "
        "if that prefix is still in Groq's cache."
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
    shared.add_argument("--max-tokens", type=int, default=64)
    shared.add_argument("--prefix-repeats", type=int, default=40, help="How many times to repeat the static prefix block")
    shared.add_argument("--pause", type=float, default=0.0, help="Seconds to wait between turns")

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
    cold.add_argument("--question", default="In one paragraph, explain why the static prefix must come first.")
    cold.set_defaults(func=cmd_cold_warm)

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
