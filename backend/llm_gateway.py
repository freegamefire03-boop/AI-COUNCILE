"""
LLM Gateway — OpenRouter free-tier.
Primary: openrouter/free (auto-routes to available free models).
Fallback: known :free model IDs.
"""

import time, random, json, requests

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# openrouter/free = OpenRouter's Free Models Router (Feb 2026)
# Routes automatically to available free models. Always free.
FREE_ROUTER = "openrouter/free"

# Hardcoded fallbacks in case openrouter/free is down
FALLBACK_FREE_MODELS = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-4-scout:free",
    "qwen/qwen3-8b:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
    "microsoft/phi-4:free",
    "google/gemma-3-12b-it:free",
]

REQUEST_HEADERS_TEMPLATE = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://freegamefire03-boop.github.io/AI-COUNCILE/",
    "X-Title": "Planning Council v0",
}

GATEWAY_CONFIG = {
    "min_interval_seconds": 4,
    "max_retries": 3,
    "timeout_seconds": 90,
    "backoff_base": 6,
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
    """
    Return list of free model IDs.
    Uses openrouter/free as primary — no discovery call needed.
    Discovery is optional and only done to build fallback list.
    """
    try:
        resp = requests.get(
            f"{OPENROUTER_BASE}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return FALLBACK_FREE_MODELS[:]
        models = resp.json().get("data", [])
        free = [FREE_ROUTER]  # always first
        for m in models:
            mid = m.get("id", "")
            pricing = m.get("pricing", {})
            p = str(pricing.get("prompt", "1"))
            c = str(pricing.get("completion", "1"))
            if mid.endswith(":free") or (p == "0" and c == "0"):
                if mid not in free:
                    free.append(mid)
        print(f"[gateway] {len(free)} free models available.")
        return free
    except Exception as e:
        print(f"[gateway] Discovery failed ({e}), using fallback list.")
        return FALLBACK_FREE_MODELS[:]


def call_llm(api_key: str, messages: list, system: str = None,
             model: str = None, max_tokens: int = 1500,
             free_models: list = None) -> str:
    global _last_call_time

    if free_models is None:
        free_models = FALLBACK_FREE_MODELS[:]
    if model is None:
        model = FREE_ROUTER  # default: free router

    headers = {**REQUEST_HEADERS_TEMPLATE, "Authorization": f"Bearer {api_key}"}

    payload_messages = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    last_error = None
    for attempt in range(1, GATEWAY_CONFIG["max_retries"] + 1):
        # Rotate model on retry
        if attempt == 1:
            chosen = model
        else:
            chosen = free_models[attempt % len(free_models)]
            print(f"[gateway] Retry {attempt}: switching to {chosen}")

        _wait_interval()

        payload = {
            "model": chosen,
            "messages": payload_messages,
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }

        print(f"[gateway] Attempt {attempt} | model={chosen}")
        try:
            resp = requests.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=headers, json=payload,
                timeout=GATEWAY_CONFIG["timeout_seconds"],
            )
            _last_call_time = time.time()

            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                used = data.get("model", chosen)
                usage = data.get("usage", {})
                print(f"[gateway] OK | model={used} | tokens={usage}")
                return content.strip()

            elif resp.status_code == 429:
                backoff = GATEWAY_CONFIG["backoff_base"] * (GATEWAY_CONFIG["backoff_multiplier"] ** (attempt-1)) + _jitter()
                print(f"[gateway] 429 rate limit. Wait {backoff:.1f}s")
                time.sleep(backoff)
                last_error = "Rate limited 429"

            elif resp.status_code in (502, 503, 504):
                backoff = GATEWAY_CONFIG["backoff_base"] * attempt + _jitter()
                print(f"[gateway] {resp.status_code} server error. Wait {backoff:.1f}s")
                time.sleep(backoff)
                last_error = f"Server error {resp.status_code}"

            else:
                body = resp.text[:400]
                print(f"[gateway] HTTP {resp.status_code}: {body}")
                last_error = f"HTTP {resp.status_code}: {body}"
                time.sleep(GATEWAY_CONFIG["backoff_base"] + _jitter())

        except requests.Timeout:
            last_error = "Timeout"
            print(f"[gateway] Timeout on attempt {attempt}")
            time.sleep(GATEWAY_CONFIG["backoff_base"] + _jitter())
        except Exception as e:
            last_error = str(e)
            print(f"[gateway] Exception: {e}")
            time.sleep(GATEWAY_CONFIG["backoff_base"] + _jitter())

    raise RuntimeError(f"All {GATEWAY_CONFIG['max_retries']} attempts failed. Last: {last_error}")


def call_llm_json(api_key: str, messages: list, system: str = None,
                  model: str = None, max_tokens: int = 1500,
                  free_models: list = None) -> dict:
    raw = call_llm(api_key, messages, system=system, model=model,
                   max_tokens=max_tokens, free_models=free_models)

    def try_parse(text: str) -> dict:
        text = text.strip()
        if "```" in text:
            lines = text.split("\n")
            inner, in_block = [], False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True; continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    inner.append(line)
            text = "\n".join(inner).strip()
        # Try to find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
        return json.loads(text)

    try:
        return try_parse(raw)
    except json.JSONDecodeError:
        print("[gateway] JSON parse failed. Attempting LLM repair...")
        repair = [{"role": "user", "content":
            "Fix this JSON (return ONLY valid JSON, no markdown):\n\n" + raw[:3000]}]
        repaired = call_llm(api_key, repair, max_tokens=max_tokens, free_models=free_models)
        try:
            return try_parse(repaired)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON repair failed: {e}\nRaw: {raw[:400]}")
