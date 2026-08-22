"""
LLM Gateway — OpenRouter free-tier with retry, backoff, and model discovery.
"""

import time
import random
import json
import requests

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Auto-router: picks from available free models automatically
AUTO_FREE_ROUTER = "openrouter/auto"

# Hardcoded fallback free models (as of Aug 2026 — rotates frequently)
FALLBACK_FREE_MODELS = [
    "openrouter/auto",           # OpenRouter auto-router (always try first)
    "meta-llama/llama-4-scout:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-12b-it:free",
    "microsoft/phi-4:free",
    "qwen/qwen3-8b:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
]

REQUEST_HEADERS_TEMPLATE = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://freegamefire03-boop.github.io/planning-council-v0/",
    "X-Title": "Planning Council v0",
}

GATEWAY_CONFIG = {
    "concurrency": 1,
    "min_interval_seconds": 4,
    "max_retries": 3,
    "timeout_seconds": 120,
    "backoff_base": 5,
    "backoff_multiplier": 2,
    "jitter_max": 3,
}

_last_call_time = 0


def _wait_interval():
    global _last_call_time
    elapsed = time.time() - _last_call_time
    wait = GATEWAY_CONFIG["min_interval_seconds"] - elapsed
    if wait > 0:
        time.sleep(wait)


def _jitter():
    return random.uniform(0, GATEWAY_CONFIG["jitter_max"])


def fetch_free_models(api_key: str) -> list:
    """Fetch currently available free models from OpenRouter."""
    try:
        resp = requests.get(
            f"{OPENROUTER_BASE}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code != 200:
            return FALLBACK_FREE_MODELS[:]
        models = resp.json().get("data", [])
        free = []
        for m in models:
            mid = m.get("id", "")
            pricing = m.get("pricing", {})
            prompt_price = str(pricing.get("prompt", "1"))
            comp_price = str(pricing.get("completion", "1"))
            if mid.endswith(":free") or (prompt_price == "0" and comp_price == "0"):
                free.append(mid)
        if not free:
            return FALLBACK_FREE_MODELS[:]
        # Always prepend the auto-router
        if "openrouter/auto" not in free:
            free.insert(0, "openrouter/auto")
        print(f"[gateway] Discovered {len(free)} free models.")
        return free
    except Exception as e:
        print(f"[gateway] Model discovery failed: {e}. Using fallback list.")
        return FALLBACK_FREE_MODELS[:]


def call_llm(
    api_key: str,
    messages: list,
    system: str = None,
    model: str = None,
    max_tokens: int = 1500,
    free_models: list = None,
) -> str:
    """
    Call OpenRouter. Returns response text or raises RuntimeError after retries.
    """
    global _last_call_time

    if free_models is None:
        free_models = FALLBACK_FREE_MODELS[:]

    if model is None:
        model = free_models[0] if free_models else "openrouter/auto"

    headers = dict(REQUEST_HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {api_key}"

    payload_messages = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    last_error = None
    for attempt in range(1, GATEWAY_CONFIG["max_retries"] + 1):
        # Pick model for this attempt (rotate on retry)
        if attempt == 1:
            chosen_model = model
        else:
            idx = attempt % len(free_models)
            chosen_model = free_models[idx]
            print(f"[gateway] Retry {attempt}: switching to model {chosen_model}")

        _wait_interval()

        payload = {
            "model": chosen_model,
            "messages": payload_messages,
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }

        print(f"[gateway] Attempt {attempt} | model={chosen_model}")

        try:
            resp = requests.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=headers,
                json=payload,
                timeout=GATEWAY_CONFIG["timeout_seconds"],
            )
            _last_call_time = time.time()

            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                used_model = data.get("model", chosen_model)
                print(f"[gateway] Success | model_used={used_model} | tokens={data.get('usage',{})}")
                return content.strip()

            elif resp.status_code == 429:
                backoff = (
                    GATEWAY_CONFIG["backoff_base"]
                    * (GATEWAY_CONFIG["backoff_multiplier"] ** (attempt - 1))
                    + _jitter()
                )
                print(f"[gateway] Rate limited (429). Waiting {backoff:.1f}s...")
                time.sleep(backoff)
                last_error = "Rate limited (429)"

            elif resp.status_code in (502, 503, 504):
                backoff = GATEWAY_CONFIG["backoff_base"] * attempt + _jitter()
                print(f"[gateway] Server error {resp.status_code}. Waiting {backoff:.1f}s...")
                time.sleep(backoff)
                last_error = f"Server error {resp.status_code}"

            else:
                err_body = resp.text[:300]
                print(f"[gateway] HTTP {resp.status_code}: {err_body}")
                last_error = f"HTTP {resp.status_code}: {err_body}"
                if attempt < GATEWAY_CONFIG["max_retries"]:
                    time.sleep(GATEWAY_CONFIG["backoff_base"] + _jitter())

        except requests.Timeout:
            last_error = "Request timed out"
            print(f"[gateway] Timeout on attempt {attempt}.")
            time.sleep(GATEWAY_CONFIG["backoff_base"] + _jitter())

        except Exception as e:
            last_error = str(e)
            print(f"[gateway] Exception on attempt {attempt}: {e}")
            time.sleep(GATEWAY_CONFIG["backoff_base"] + _jitter())

    raise RuntimeError(f"All {GATEWAY_CONFIG['max_retries']} attempts failed. Last error: {last_error}")


def call_llm_json(
    api_key: str,
    messages: list,
    system: str = None,
    model: str = None,
    max_tokens: int = 1500,
    free_models: list = None,
) -> dict:
    """
    Call LLM and parse JSON response. One repair attempt if parsing fails.
    """
    raw = call_llm(api_key, messages, system=system, model=model,
                   max_tokens=max_tokens, free_models=free_models)

    def try_parse(text: str) -> dict:
        text = text.strip()
        # Strip markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            inner = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    inner.append(line)
            text = "\n".join(inner).strip()
        return json.loads(text)

    try:
        return try_parse(raw)
    except json.JSONDecodeError:
        print("[gateway] JSON parse failed. Attempting repair via LLM...")
        repair_prompt = [
            {
                "role": "user",
                "content": (
                    "The following text should be valid JSON but has errors. "
                    "Return ONLY the corrected JSON with no other text or markdown:\n\n"
                    + raw[:3000]
                ),
            }
        ]
        repaired = call_llm(api_key, repair_prompt, max_tokens=max_tokens,
                            free_models=free_models)
        try:
            return try_parse(repaired)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON repair failed: {e}\nRaw: {raw[:500]}")
