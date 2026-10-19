"""A tiny stand-in for Ollama, for trying PayDawg's AI step WITHOUT installing a model.

  python demo_shop/fake_ollama.py          # listens on http://127.0.0.1:11434 (Ollama's own port)

Then set LLM_PROVIDER=ollama in .env and restart PayDawg. It is NOT a real model: it applies one simple
rule so the demo is predictable. Use real Ollama (`ollama pull llama3.2`) for the real thing; PayDawg
talks to both the same way, so nothing changes in the app.

Set FAKE_MODE to change behaviour: smart (default), high, garbage, slow.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MODE = os.getenv("FAKE_MODE", "smart")


def judge(payload):
    pay, base = payload.get("payment", {}), payload.get("baseline", {}) or {}
    avg = base.get("avg_amount") or base.get("average_amount") or 0
    amount = pay.get("amount") or 0
    if avg and amount > 3 * avg:
        return {"risk_level": "medium", "reasons": [f"Amount {amount} is much higher than this shop's usual {round(avg, 2)}."]}
    return {"risk_level": "low", "reasons": ["Looks consistent with this shop's usual payments."]}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        prompt = body.get("prompt", "")
        payload = json.loads(prompt.split("Input: ", 1)[1]) if "Input: " in prompt else {}
        if MODE == "slow":
            time.sleep(30)
        if MODE == "garbage":
            answer = "I think this payment is probably fine!"
        elif MODE == "high":
            answer = json.dumps({"risk_level": "high", "reasons": ["Fake model says: very risky."]})
        else:
            answer = json.dumps(judge(payload))
        out = json.dumps({"model": body.get("model"), "response": answer, "done": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Fake Ollama ({MODE} mode) on http://127.0.0.1:11434 - not a real model. Ctrl+C to stop.")
    HTTPServer(("127.0.0.1", 11434), Handler).serve_forever()
