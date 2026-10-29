"""One bounded local transport probe; no investigation actions are dispatched."""

import hashlib
import json
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent / "transport-smoke"
OUT.mkdir(exist_ok=False)
BASE = "http://127.0.0.1:1236"
MODEL = "gpt-oss-20b-MXFP4-qualification"
request = {
    "model": MODEL,
    "messages": [
        {
            "role": "system",
            "content": "Solve the task and return the requested JSON object in your final answer.",
        },
        {
            "role": "user",
            "content": "A box contains 17 blue and 23 red parts. Remove 9 red parts and add 8 blue parts. How many parts remain? Return count and a brief arithmetic check.",
        },
    ],
    "temperature": 0,
    "max_tokens": 1400,
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "TransportSmoke",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"count": {"type": "integer"}, "check": {"type": "string"}},
                "required": ["count", "check"],
            },
        },
    },
}


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


save("request.json", request)
with httpx.Client(timeout=150, trust_env=False) as client:
    props = client.get(BASE + "/props")
    props.raise_for_status()
    save("server-props.json", props.json())
    template_request = {**request, "add_generation_prompt": True}
    template = client.post(BASE + "/apply-template", json=template_request)
    template.raise_for_status()
    save("template.json", template.json())
    prompt = template.json()["prompt"]
    tokens = client.post(
        BASE + "/tokenize", json={"content": prompt, "add_special": False, "parse_special": True}
    )
    tokens.raise_for_status()
    count = len(tokens.json()["tokens"])
    assert count + 1400 + 128 <= 16384
    start = time.monotonic()
    response = client.post(BASE + "/v1/chat/completions", json=request)
    elapsed = time.monotonic() - start
    save("http-result.json", {"status": response.status_code, "elapsed_s": elapsed})
    response.raise_for_status()
    raw = response.json()
    save("response.json", raw)
    choice = raw["choices"][0]
    message = choice["message"]
    content = message.get("content")
    parsed = json.loads(content or "")
    report = {
        "scope": "Actual local arithmetic transport test only, no vision or planner quality claim",
        "model": MODEL,
        "elapsed_s": elapsed,
        "input_tokens_preflight": count,
        "template_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "finish_reason": choice["finish_reason"],
        "final_content_separate": isinstance(content, str),
        "reasoning_content_present": bool(message.get("reasoning_content")),
        "reasoning_content_characters": len(message.get("reasoning_content") or ""),
        "parsed_final": parsed,
        "correct": parsed.get("count") == 39,
        "usage": raw.get("usage"),
        "timings": raw.get("timings"),
    }
    save("report.json", report)
    print(json.dumps(report), flush=True)
    assert choice["finish_reason"] == "stop" and parsed.get("count") == 39
