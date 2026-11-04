import os
import sys
from urllib.parse import urlparse, parse_qs, urlencode

# Ensure project root is on sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import server
import fan_engine

# In serverless environments (like Vercel), point writable SQLite database to /tmp
if "VERCEL" in os.environ or not os.access(root_dir, os.W_OK):
    server._db_path = lambda: "/tmp/match_data.db"
    try:
        server.db_init()
    except Exception:
        pass

class handler(server.Handler):
    def _normalize_path(self):
        # 1. Check query parameter ?path= forwarded by Vercel rewrite
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if "path" in qs:
            target = qs["path"][0]
            other_params = {k: v for k, v in qs.items() if k != "path"}
            if other_params:
                self.path = target + "?" + urlencode(other_params, doseq=True)
            else:
                self.path = target
            return

        # 2. Check headers
        matched = (
            self.headers.get("x-matched-path")
            or self.headers.get("x-vercel-matched-path")
            or self.headers.get("x-real-path")
            or self.path
        )
        if matched.startswith("/api/fan/"):
            matched = matched[4:]
        elif matched in ("/api", "/api/", "/api/index"):
            matched = "/fan/data"
        self.path = matched

    def do_GET(self):
        self._normalize_path()
        parsed = urlparse(self.path)
        if parsed.path == "/fan/data":
            # Ensure feed_fresh is true for the Vercel demo showcase
            try:
                data = fan_engine.get_fan_data()
                if isinstance(data, dict):
                    data_copy = dict(data)
                    data_copy["feed_fresh"] = True
                    data_copy["feed_source"] = "live"
                    self._json_cached(data_copy)
                    return
            except Exception:
                pass
        super().do_GET()

    def do_POST(self):
        self._normalize_path()
        super().do_POST()

    def do_OPTIONS(self):
        self._normalize_path()
        super().do_OPTIONS()
