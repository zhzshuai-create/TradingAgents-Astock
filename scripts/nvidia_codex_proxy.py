"""
NVIDIA NIM → Codex Proxy
Translates Codex Responses API ↔ NVIDIA Chat Completions API
"""
import json, os, time, sys, traceback
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

NVIDIA_BASE = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_KEY = os.getenv("NVIDIA_API_KEY", "")
API_KEY = os.getenv("PROXY_API_KEY", "nvapi-proxy")
PORT = int(os.getenv("PROXY_PORT", "8317"))

app = FastAPI(title="NVIDIA-Codex Proxy")

AVAILABLE_MODELS = [
    {
        "id": "z-ai/glm-5.2",
        "object": "model",
        "owned_by": "nvidia",
        "created": 1750000000,
        "capabilities": {
            "supports_tool_calls": True,
            "supports_parallel_tool_calls": True,
            "supports_images": False,
            "supports_audio": False,
            "supports_computer_use": False,
            "supports_prompt_caching": False,
            "supports_streaming": True,
        },
        "context_window": 200000,
        "max_output_tokens": 16384,
        "pricing": {"prompt": 0, "completion": 0},
    },
    {
        "id": "deepseek-ai/deepseek-v4-pro",
        "object": "model", "owned_by": "nvidia", "created": 1750000000,
        "capabilities": {
            "supports_tool_calls": True, "supports_parallel_tool_calls": True,
            "supports_images": False, "supports_audio": False,
            "supports_computer_use": False, "supports_prompt_caching": False,
            "supports_streaming": True,
        },
        "context_window": 131072, "max_output_tokens": 16384,
        "pricing": {"prompt": 0, "completion": 0},
    },
    {
        "id": "deepseek-ai/deepseek-v4-flash",
        "object": "model", "owned_by": "nvidia", "created": 1750000000,
        "capabilities": {
            "supports_tool_calls": True, "supports_parallel_tool_calls": True,
            "supports_images": False, "supports_audio": False,
            "supports_computer_use": False, "supports_prompt_caching": False,
            "supports_streaming": True,
        },
        "context_window": 131072, "max_output_tokens": 16384,
        "pricing": {"prompt": 0, "completion": 0},
    },
    {
        "id": "minimaxai/minimax-m3",
        "object": "model", "owned_by": "nvidia", "created": 1750000000,
        "capabilities": {
            "supports_tool_calls": True, "supports_parallel_tool_calls": True,
            "supports_images": False, "supports_audio": False,
            "supports_computer_use": False, "supports_prompt_caching": True,
            "supports_streaming": True,
        },
        "context_window": 1048576, "max_output_tokens": 16384,
        "pricing": {"prompt": 0, "completion": 0},
    },
    {
        "id": "moonshotai/kimi-k2.6",
        "object": "model", "owned_by": "nvidia", "created": 1750000000,
        "capabilities": {
            "supports_tool_calls": True, "supports_parallel_tool_calls": True,
            "supports_images": False, "supports_audio": False,
            "supports_computer_use": False, "supports_prompt_caching": False,
            "supports_streaming": True,
        },
        "context_window": 131072, "max_output_tokens": 16384,
        "pricing": {"prompt": 0, "completion": 0},
    },
]


def _check_auth(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.replace("Bearer ", "") == API_KEY


@app.get("/v1/models")
async def list_models(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, 401)
    return {"object": "list", "data": AVAILABLE_MODELS}


@app.post("/v1/responses")
async def responses_api(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, 401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, 400)

    model = body.get("model", "z-ai/glm-5.2")
    user_input = body.get("input", "")
    stream = body.get("stream", False)
    max_tokens = body.get("max_output_tokens") or body.get("max_tokens") or 4096

    # Build messages
    if isinstance(user_input, str):
        messages = [{"role": "user", "content": user_input}]
    elif isinstance(user_input, list):
        messages = []
        for block in user_input:
            if isinstance(block, dict):
                role = block.get("role", "user")
                content = block.get("content", "")
                if isinstance(content, list):
                    # content blocks: [{type: "input_text", text: "..."}]
                    text_parts = []
                    for c in content:
                        if isinstance(c, dict):
                            text_parts.append(c.get("text", ""))
                        elif isinstance(c, str):
                            text_parts.append(c)
                    messages.append({"role": role, "content": " ".join(text_parts)})
                else:
                    messages.append({"role": role, "content": str(content)})
            elif isinstance(block, str):
                messages.append({"role": "user", "content": block})
    else:
        messages = [{"role": "user", "content": str(user_input)}]

    chat_body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    for key in ("temperature", "top_p", "stop"):
        if key in body and body[key] is not None:
            chat_body[key] = body[key]

    headers = {
        "Authorization": f"Bearer {NVIDIA_KEY}",
        "Content-Type": "application/json",
    }

    print(f"[proxy] {model} stream={stream}", file=sys.stderr)

    try:
        if stream:
            async def _stream():
                import asyncio
                resp_id = f"resp_{int(time.time())}"
                yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': resp_id, 'object': 'response', 'model': model, 'status': 'in_progress'}})}\n\n"
                yield f"data: {json.dumps({'type': 'response.in_progress', 'response': {'id': resp_id, 'object': 'response', 'model': model, 'status': 'in_progress'}})}\n\n"

                # Use sync httpx in a thread to avoid FastAPI stream cancellation issues
                def _sync_fetch():
                    results = []
                    with httpx.Client(timeout=600) as client:
                        with client.stream("POST", f"{NVIDIA_BASE}/chat/completions", json=chat_body, headers=headers) as resp:
                            if resp.status_code != 200:
                                results.append(("error", resp.status_code, resp.read().decode(errors="replace")[:500]))
                                return results
                            for line in resp.iter_lines():
                                if not line:
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[6:]
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk_json = json.loads(data_str)
                                        choices = chunk_json.get("choices", [])
                                        if choices:
                                            delta = choices[0].get("delta", {})
                                            content = delta.get("content", "")
                                            if content:
                                                results.append(("delta", content))
                                    except json.JSONDecodeError:
                                        pass
                    return results

                results = await asyncio.to_thread(_sync_fetch)
                accumulated = ""
                for item in results:
                    rtype = item[0]
                    if rtype == "error":
                        err_msg = str(item[1:])
                        print(f"[proxy:stream] upstream error: {err_msg[:200]}", file=sys.stderr)
                        yield f"data: {json.dumps({'type': 'error', 'error': {'message': err_msg}})}\n\n"
                        yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'object': 'response', 'model': model, 'status': 'failed', 'status_details': {'error': {'message': err_msg}}}})}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    elif rtype == "delta":
                        content = item[1]
                        accumulated += content
                        yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': f'{resp_id}_msg', 'output_index': 0, 'content_index': 0, 'delta': content}, ensure_ascii=False)}\n\n"

                print(f"[proxy:stream] done, accumulated={len(accumulated)} chars", file=sys.stderr)

                # Send completion events
                yield f"data: {json.dumps({'type': 'response.output_text.done', 'item_id': f'{resp_id}_msg', 'output_index': 0, 'content_index': 0, 'text': accumulated}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'response.content_part.done', 'item_id': f'{resp_id}_msg', 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': accumulated}}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'object': 'response', 'model': model, 'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': accumulated}]}]}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_stream(), media_type="text/event-stream",
                                     headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})

        # Non-streaming
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{NVIDIA_BASE}/chat/completions",
                json=chat_body, headers=headers
            )

        if resp.status_code != 200:
            print(f"[proxy] NVIDIA error {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            return JSONResponse({"error": f"upstream error: {resp.status_code}"}, 502)

        data = resp.json()
        choices = data.get("choices", [])
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage", {})

        result = {
            "id": data.get("id", f"resp_{int(time.time())}"),
            "object": "response",
            "model": model,
            "output": [{
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }],
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }
        print(f"[proxy] ← {len(content)} chars  tokens={result['usage']['total_tokens']}", file=sys.stderr)
        return result

    except Exception as e:
        print(f"[proxy] ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return JSONResponse({"error": str(e)}, 500)


@app.get("/health")
async def health():
    return {"status": "ok", "backend": NVIDIA_BASE}


if __name__ == "__main__":
    import uvicorn
    if not NVIDIA_KEY:
        print("ERROR: NVIDIA_API_KEY not set!", file=sys.stderr)
        exit(1)
    print(f"Proxy: http://localhost:{PORT} → {NVIDIA_BASE}", file=sys.stderr)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
