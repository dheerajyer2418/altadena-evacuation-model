"""Serve the live UI locally and open it in a browser.

    python -m scripts.serve_ui            # http://localhost:8000/ui/index.html
    python -m scripts.serve_ui --port 8777 --no-open

Serves the PROJECT ROOT so ui/index.html can fetch outputs/ui/*.json (avoids the
file:// CORS restriction). Generate replays first with scripts.export_replay.
"""
from __future__ import annotations

import argparse
import http.server
import socketserver
import webbrowser
from functools import partial

from altadena_evac.config import project_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    root = str(project_path())
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=root)

    idx = project_path("outputs", "ui", "index.json")
    if not idx.exists():
        print("WARNING: no replays found (outputs/ui/index.json missing).")
        print("Generate one first, e.g.:")
        print("  python -m scripts.export_replay --mode altadena --fleet 0 --label 'No-AV baseline'")

    url = f"http://localhost:{args.port}/ui/index.html"
    # allow quick restarts without 'address already in use'
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"serving {root}")
        print(f"open:  {url}")
        if not args.no_open:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
