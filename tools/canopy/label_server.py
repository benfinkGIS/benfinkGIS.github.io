"""Local server for the accuracy labelling page.

Serves tools/canopy-label/ and the image chips, and saves each label to
tucson-canopy/work/accuracy/labels.json as it is made, so nothing has to be
exported by hand. Listens on this computer only.

Run:  py tools/canopy/label_server.py [port]      then open http://localhost:8770/

The page is given points.json (ids in shuffled order). It is never given
key.json, which holds each point's site and mapped class.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "tools" / "canopy-label"
DATA = ROOT / "tucson-canopy" / "work" / "accuracy"
LABELS = DATA / "labels.json"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
         ".css": "text/css", ".jpg": "image/jpeg", ".json": "application/json"}
VALID = {0, 1, 2, 3, 4, 5, 6}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/labels":
            body = LABELS.read_bytes() if LABELS.exists() else b"{}"
            return self.send(200, body)
        if path == "/points.json":
            target = DATA / "points.json"
        elif path.startswith("/chips/"):
            target = DATA / "chips" / Path(path).name
        else:
            target = PAGE / (Path(path).name or "index.html")
        if target.suffix not in TYPES or not target.is_file():
            return self.send(404, b"not found", "text/plain")
        self.send(200, target.read_bytes(), TYPES[target.suffix])

    def do_POST(self):
        if self.path != "/labels":
            return self.send(404, b"not found", "text/plain")
        try:
            item = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ids = set(json.loads((DATA / "points.json").read_text())["ids"])
            pid, label = item["id"], item["label"]
            if pid not in ids or (label is not None and label not in VALID):
                raise ValueError("unknown point or label")
        except (ValueError, KeyError, TypeError) as err:
            return self.send(400, str(err).encode(), "text/plain")
        labels = json.loads(LABELS.read_text()) if LABELS.exists() else {}
        if label is None:
            labels.pop(pid, None)
        else:
            labels[pid] = dict(label=label, at=item.get("at"))
        tmp = LABELS.with_suffix(".tmp")
        tmp.write_text(json.dumps(labels, indent=1))
        tmp.replace(LABELS)
        self.send(200, json.dumps(dict(saved=len(labels))).encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    print(f"labelling page on http://localhost:{port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
