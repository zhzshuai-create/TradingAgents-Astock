"""
NVIDIA NIM → Codex Proxy (simple synchronous HTTP server)
"""
import json, os, sys, time, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
import httpx

NVIDIA_BASE = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_KEY = os.getenv("NVIDIA_API_KEY", "")
API_KEY = os.getenv("PROXY_API_KEY", "nvapi-proxy")
PORT = int(os.getenv("PROXY_PORT", "8317"))


class ProxyHandler(BaseHTTPRequestHandler):

    def _check_auth(self):
        auth = self.headers.get("Authorization", "")
        return auth.replace("Bearer ", "") == API_KEY

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, data_str):
        chunk = f"data: {data_str}\n\n".encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()

    def do_GET(self):
        if not self._check_auth():
            self._send_json({"error": "unauthorized"}, 401)
            return

        if self.path == "/health":
            self._send_json({"status": "ok", "backend": NVIDIA_BASE})
        elif self.path == "/v1/models":
            self._send_json({"object": "list", "data": [
                {"id": "z-ai/glm-5.2", "object": "model", "owned_by": "nvidia",
                 "capabilities": {"supports_tool_calls": True, "supports_streaming": True},
                 "context_window": 200000, "max_output_tokens": 16384},
                {"id": "deepseek-ai/deepseek-v4-pro", "object": "model", "owned_by": "nvidia",
                 "capabilities": {"supports_tool_calls": True, "supports_streaming": True},
                 "context_window": 131072, "max_output_tokens": 16384},
            ]})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._check_auth():
            self._send_json({"error": "unauthorized"}, 401)
            return

        if self.path != "/v1/responses":
            self._send_json({"error": "not found"}, 404)
            return

        # Read request body
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len))

        model = body.get("model", "z-ai/glm-5.2")
        user_input = body.get("input", "")
        stream = body.get("stream", False)
        max_tokens = body.get("max_output_tokens") or body.get("max_tokens") or 4096

        # Build chat messages from Responses API format
        if isinstance(user_input, str):
            messages = [{"role": "user", "content": user_input}]
        elif isinstance(user_input, list):
            messages = []
            for block in user_input:
                if isinstance(block, dict):
                    role = block.get("role", "user")
                    content = block.get("content", "")
                    if isinstance(content, list):
                        texts = []
                        for c in content:
                            texts.append(c.get("text", "") if isinstance(c, dict) else str(c))
                        messages.append({"role": role, "content": " ".join(texts)})
                    else:
                        messages.append({"role": role, "content": str(content)})
                elif isinstance(block, str):
                    messages.append({"role": "user", "content": block})
        else:
            messages = [{"role": "user", "content": str(user_input)}]

        chat_body = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": stream}
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
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                resp_id = f"resp_{int(time.time())}"
                self._send_sse(json.dumps({"type": "response.created", "response": {"id": resp_id, "object": "response", "model": model, "status": "in_progress"}}, ensure_ascii=False))
                self._send_sse(json.dumps({"type": "response.in_progress", "response": {"id": resp_id, "object": "response", "model": model, "status": "in_progress"}}, ensure_ascii=False))

                accumulated = ""
                with httpx.Client(timeout=600) as client:
                    with client.stream("POST", f"{NVIDIA_BASE}/chat/completions", json=chat_body, headers=headers) as resp:
                        if resp.status_code != 200:
                            err = resp.read().decode(errors="replace")[:500]
                            self._send_sse(json.dumps({"type": "error", "error": {"message": f"upstream {resp.status_code}: {err}"}}))
                            self._send_sse(json.dumps({"type": "response.completed", "response": {"id": resp_id, "object": "response", "model": model, "status": "failed", "status_details": {"error": {"message": err}}}}))
                            self._send_sse("[DONE]")
                            return

                        for line in resp.iter_lines():
                            if not line:
                                continue
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    choices = chunk.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            accumulated += content
                                            self._send_sse(json.dumps({"type": "response.output_text.delta", "item_id": f"{resp_id}_msg", "output_index": 0, "content_index": 0, "delta": content}, ensure_ascii=False))
                                except json.JSONDecodeError:
                                    pass

                self._send_sse(json.dumps({"type": "response.output_text.done", "item_id": f"{resp_id}_msg", "output_index": 0, "content_index": 0, "text": accumulated}, ensure_ascii=False))
                self._send_sse(json.dumps({"type": "response.content_part.done", "item_id": f"{resp_id}_msg", "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": accumulated}}, ensure_ascii=False))
                self._send_sse(json.dumps({"type": "response.completed", "response": {"id": resp_id, "object": "response", "model": model, "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": accumulated}]}]}}, ensure_ascii=False))
                self._send_sse("[DONE]")
                print(f"[proxy:stream] done, {len(accumulated)} chars", file=sys.stderr)

            else:
                # Non-streaming
                with httpx.Client(timeout=300) as client:
                    resp = client.post(f"{NVIDIA_BASE}/chat/completions", json=chat_body, headers=headers)

                if resp.status_code != 200:
                    self._send_json({"error": f"upstream: {resp.status_code}"}, 502)
                    return

                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                usage = data.get("usage", {})

                self._send_json({
                    "id": data.get("id", f"resp_{int(time.time())}"),
                    "object": "response", "model": model,
                    "output": [{"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": content}]}],
                    "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                              "output_tokens": usage.get("completion_tokens", 0),
                              "total_tokens": usage.get("total_tokens", 0)},
                })

        except Exception as e:
            print(f"[proxy] ERROR: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            try:
                self._send_json({"error": str(e)}, 500)
            except:
                pass

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging


if __name__ == "__main__":
    if not NVIDIA_KEY:
        print("ERROR: NVIDIA_API_KEY not set!", file=sys.stderr)
        sys.exit(1)
    print(f"Proxy: http://localhost:{PORT} → {NVIDIA_BASE}", file=sys.stderr)
    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    server.serve_forever()
