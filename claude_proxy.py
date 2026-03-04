#!/usr/bin/env python3
"""Lightweight HTTP proxy that wraps `claude -p` for Docker containers.

Run on the host so the containerized app can reach Claude Code:

    python claude_proxy.py                  # 0.0.0.0:9100
    python claude_proxy.py --port 9200      # custom port
"""

import argparse
import json
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            body = json.dumps({
                'status': 'ok',
                'claude_available': shutil.which('claude') is not None,
            })
            self._respond(200, body)
        else:
            self._respond(404, json.dumps({'error': 'not found'}))

    def do_POST(self):
        if self.path != '/summarize':
            self._respond(404, json.dumps({'error': 'not found'}))
            return

        # Read request body
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._respond(400, json.dumps({'error': 'invalid JSON'}))
            return

        prompt = data.get('prompt', '')
        text = data.get('text', '')
        if not text:
            self._respond(400, json.dumps({'error': 'missing "text" field'}))
            return

        if not shutil.which('claude'):
            self._respond(503, json.dumps({'error': 'claude CLI not found on host'}))
            return

        try:
            result = subprocess.run(
                ['claude', '-p', prompt, '--stdin'],
                input=text,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            self._respond(504, json.dumps({'error': 'claude CLI timed out'}))
            return

        if result.returncode != 0:
            self._respond(502, json.dumps({
                'error': 'claude CLI failed',
                'detail': result.stderr.strip(),
            }))
            return

        body = json.dumps({'summary': result.stdout.strip()})
        self._respond(200, body)

    def _respond(self, status: int, body: str):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, fmt, *args):
        # Use simple print to avoid BaseHTTPRequestHandler's stderr format
        print(f"[proxy] {args[0]}" if args else fmt)


def main():
    parser = argparse.ArgumentParser(description='Claude Code HTTP proxy')
    parser.add_argument('--host', default='0.0.0.0', help='Bind address (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9100, help='Port (default: 9100)')
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), ProxyHandler)
    print(f"Claude proxy listening on {args.host}:{args.port}")
    print(f"Claude CLI available: {shutil.which('claude') is not None}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == '__main__':
    main()
