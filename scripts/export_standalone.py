"""Bundle the UI + replays into ONE self-contained HTML (no server needed).

    python -m scripts.export_standalone

Writes altadena_live.html at the project root. Double-click it (opens via file://)
— all replays listed in outputs/ui/index.json are embedded, and deck.gl is inlined
so it works even without the CDN. Use this if localhost/the dev server won't open.
"""
from __future__ import annotations

import json

import requests

from altadena_evac.config import project_path

DECK_URL = "https://unpkg.com/deck.gl@9.0.0/dist.min.js"
CDN_TAG = f'<script src="{DECK_URL}"></script>'


def main():
    ui = project_path("ui", "index.html").read_text(encoding="utf-8")
    ui_dir = project_path("outputs", "ui")
    index = json.loads((ui_dir / "index.json").read_text(encoding="utf-8"))

    replays = {}
    for entry in index.values():
        f = entry["file"]
        replays[f] = json.loads((ui_dir / f).read_text(encoding="utf-8"))
    total_mb = sum((ui_dir / e["file"]).stat().st_size for e in index.values()) / 1e6
    print(f"embedding {len(replays)} replays (~{total_mb:.1f} MB of data)")

    # inline deck.gl so no CDN is required
    try:
        js = requests.get(DECK_URL, timeout=60).text
        ui = ui.replace(CDN_TAG, f"<script>/* deck.gl@9.0.0 inlined */\n{js}\n</script>")
        print("  inlined deck.gl (offline-capable)")
    except Exception as e:  # noqa: BLE001
        print(f"  could not inline deck.gl ({type(e).__name__}); keeping CDN link "
              f"(needs internet to load the map library)")

    # embed data as JSON strings parsed at runtime (fast + safe escaping)
    data_script = (
        "<script>\n"
        f"window.__INDEX__=JSON.parse({json.dumps(json.dumps(index))});\n"
        f"window.__REPLAYS__=JSON.parse({json.dumps(json.dumps(replays))});\n"
        "</script>\n"
    )
    # inject right before the app script (the last <script> block)
    marker = "<script>\nconst $ = s => document.querySelector(s);"
    if marker in ui:
        ui = ui.replace(marker, data_script + marker, 1)
    else:  # fallback: before </body>
        ui = ui.replace("</body>", data_script + "</body>", 1)

    out = project_path("altadena_live.html")
    out.write_text(ui, encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")
    print("Double-click altadena_live.html in Explorer — no server needed.")


if __name__ == "__main__":
    main()
