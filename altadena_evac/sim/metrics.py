"""Result summarization and CSV/JSON writers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _pct(a, q):
    return float(np.percentile(a, q)) if len(a) else None


def summarize(result: dict) -> dict:
    """Flatten one run's result into a comparison row (requirement 9 metrics)."""
    present = result["n_persons_present"]
    reached = result["n_reached_safety"]
    row = {
        "policy": result["meta"]["policy"],
        "fleet_size": result["meta"]["fleet_size"],
        "seed_behavior": result["meta"]["seeds"]["behavior"],
        "seed_dispatch": result["meta"]["seeds"]["dispatch"],
        "seed_hazard": result["meta"]["seeds"]["hazard"],
        "n_present": present,
        "n_reached": reached,
        "reached_frac": round(reached / present, 4) if present else None,
        "n_not_reached": result["n_not_reached"],
        "n_exposed": result["n_exposed_persons"],
        "total_exposure_person_min": round(result["total_exposure_person_s"] / 60.0, 1),
        "full_clearance": result["full_clearance"],
        "clearance_time_min": (round(result["clearance_time_s"] / 60.0, 1)
                               if result["clearance_time_s"] is not None else None),
        "n_trapped_vehicles": result["n_trapped_vehicles"],
        "n_stranded": result["n_stranded_no_fleet_or_overflow"],
    }
    disp = result.get("dispatch")
    if disp:
        waits = disp["pickup_waits_s"]
        row.update({
            "av_requests": disp["n_requests"],
            "av_served_requests": disp["served_requests"],
            "av_unserved_requests": disp["unserved_requests"],
            "av_served_persons": disp["served_persons"],
            "av_unserved_persons": disp["unserved_persons"],
            "pickup_wait_median_min": (round(_pct(waits, 50) / 60.0, 1) if waits else None),
            "pickup_wait_p90_min": (round(_pct(waits, 90) / 60.0, 1) if waits else None),
            "withdrawn": disp["withdrawn"],
        })
    # carless-specific outcome (the research focus)
    bva = result["breakdowns"]["by_vehicle_access"].get("no_vehicle")
    if bva:
        row["carless_reached_frac"] = bva["reached_frac"]
        row["carless_n"] = bva["n"]
    return row


def write_json(obj, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=_json_default)
    return path


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return list(o)
    return str(o)


def write_rows_csv(rows: list[dict], path: str | Path):
    import csv
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return path
    keys = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path
