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
        # Route root path "/" directly to the Fan Companion UI
        if self.path == "/" or self.path.startswith("/?"):
            self.path = "/fan"
        super().do_GET()
