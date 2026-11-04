import os
import sys

# Ensure project root is on sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import server

# In serverless environments (like Vercel), point writable SQLite database to /tmp
if "VERCEL" in os.environ or not os.access(root_dir, os.W_OK):
    server._db_path = lambda: "/tmp/match_data.db"
    try:
        server.db_init()
    except Exception:
        pass

class handler(server.Handler):
    def _normalize_path(self):
        # Read the real incoming URL from Vercel headers if available
        matched = (
            self.headers.get("x-matched-path")
            or self.headers.get("x-vercel-matched-path")
            or self.headers.get("x-real-path")
            or self.path
        )
        if matched.startswith("/api/fan/"):
            matched = matched[4:]
        elif matched in ("/api", "/api/"):
            matched = "/fan/data"
        self.path = matched

    def do_GET(self):
        self._normalize_path()
        super().do_GET()

    def do_POST(self):
        self._normalize_path()
        super().do_POST()

    def do_OPTIONS(self):
        self._normalize_path()
        super().do_OPTIONS()
