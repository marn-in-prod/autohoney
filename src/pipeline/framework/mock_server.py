#!/usr/bin/env python3
"""Mock server for honeypot testing."""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        print(f"RECEIVED POST to {self.path}:", flush=True)
        print(body, flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": "ok", "message": "Request received"}).encode()
        )

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": "ok", "service": "Mock Server"}).encode()
        )

    def log_message(self, format, *args):
        print(f"{args[0]}", flush=True)


if __name__ == "__main__":
    print("Mock server running on port 80...", flush=True)
    HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
