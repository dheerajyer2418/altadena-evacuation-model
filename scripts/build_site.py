"""Assemble a static site for free hosting (e.g. GitHub Pages) into ./docs.

    python -m scripts.build_site

The web app is 100% client-side, so hosting is just static files. This copies
the UI + the replay data + chart PNGs into ./docs and rewrites the data paths so
everything resolves from the site root. Deploy ./docs (GitHub Pages: Settings →
Pages → Deploy from branch → main → /docs).
"""
from __future__ import annotations

import shutil

from altadena_evac.config import project_path


def main():
    root = project_path()
    docs = root / "docs"
    src_ui = root / "outputs" / "ui"
    if not (src_ui / "index.json").exists():
        raise SystemExit("No replays found. Run scripts.export_replay (and "
                         "scripts.make_charts) first.")

    # fresh docs/
    if docs.exists():
        shutil.rmtree(docs)
    (docs / "charts").mkdir(parents=True)

    # app html: data paths change from '../outputs/ui/' (dev) to './' (site root)
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    html = html.replace("../outputs/ui/", "./")
    (docs / "index.html").write_text(html, encoding="utf-8")

    # data + charts
    shutil.copy2(src_ui / "index.json", docs / "index.json")
    for rep in src_ui.glob("replay_*.json"):
        shutil.copy2(rep, docs / rep.name)
    charts = src_ui / "charts"
    n_charts = 0
    if charts.exists():
        for png in charts.glob("*.png"):
            shutil.copy2(png, docs / "charts" / png.name)
            n_charts += 1

    # GitHub Pages: skip Jekyll so nothing is filtered out
    (docs / ".nojekyll").write_text("", encoding="utf-8")

    size = sum(f.stat().st_size for f in docs.rglob("*") if f.is_file()) / 1e6
    n_rep = len(list(docs.glob("replay_*.json")))
    print(f"built ./docs  ({size:.1f} MB, {n_rep} replays, {n_charts} charts)")
    print("Deploy: push to GitHub, then Settings > Pages > main branch > /docs.")


if __name__ == "__main__":
    main()
