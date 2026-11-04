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
    def do_GET(self):
        # Support Vercel x-matched-path or original path
        orig_path = self.headers.get("x-matched-path") or self.headers.get("x-vercel-matched-path") or self.path
        if orig_path.startswith("/fan/") or orig_path == "/fan":
            self.path = orig_path
        elif self.path in ("/", "/index.html", "/api", "/api/index.py"):
            try:
                html_path = os.path.join(root_dir, "fan.html")
                with open(html_path, "r", encoding="utf-8") as f:
                    self._html(f.read())
                return
            except Exception:
                pass
        super().do_GET()

    def do_POST(self):
        orig_path = self.headers.get("x-matched-path") or self.headers.get("x-vercel-matched-path") or self.path
        if orig_path.startswith("/fan/"):
            self.path = orig_path
        super().do_POST()
