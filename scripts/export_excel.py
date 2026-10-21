"""Compile the model's results into a single multi-sheet Excel workbook.

    python -m scripts.export_excel

Writes outputs/altadena_results.xlsx with:
  * READ ME            — what this is + the honest caveats
  * Scenario results   — every replay run (incl. the real-population ones)
  * Policy comparison… — each comparison CSV that exists, one sheet apiece
  * Population fit      — IPU fit error per Altadena neighborhood (block group)
  * Data sources        — where each input came from

Reads whatever result files are present; missing ones are skipped (not faked).
"""
from __future__ import annotations

import json

import pandas as pd

from altadena_evac.config import project_path


def _readme_df() -> pd.DataFrame:
    lines = [
        "ALTADENA WILDFIRE EVACUATION MODEL — RESULTS",
        "",
        "PLEASE READ FIRST:",
        "• These are HYPOTHETICAL 'what-if' scenarios, NOT a reconstruction of the",
        "  January-2025 Eaton Fire and NOT a prediction of real outcomes.",
        "• The fire is invented and the traffic model is NOT calibrated to real",
        "  Altadena traffic (no INRIX/count data were used).",
        "• Therefore the numbers are only meaningful as a RELATIVE COMPARISON between",
        "  strategies, which are all run on the exact same population and fire.",
        "• The software is tested (29 automated checks); real-world accuracy is NOT",
        "  externally validated.",
        "",
        "KEY TERMS:",
        "• reached_frac        = fraction of people present who reached safety.",
        "• carless_reached_frac = same, but only for households without a car (the focus).",
        "• n_exposed           = people the fire front reached (a danger signal, NOT a",
        "                        casualty count).",
        "• full_clearance      = did EVERYONE present reach safety? (clearance time is",
        "                        only reported when this is true).",
        "",
        "POPULATION: a Census-based synthetic stand-in for Altadena, ~15,000 households",
        "/ ~41,000 people, within ~1% of official ACS totals (mean fit error SRMSE≈0.06).",
        "Carless households are slightly overcounted (~4.5% vs ACS 3.7%) — treat that",
        "exact number as approximate.",
        "",
        "SHEETS IN THIS WORKBOOK:",
        "• 'Scenario results'  — one row per simulation run (the live-UI scenarios).",
        "• 'Policy cmp …'      — policy x fleet-size grids (toy and real-road runs).",
        "• 'Population fit'     — synthesis fit error per neighborhood.",
        "• 'Data sources'      — provenance of every input.",
    ]
    return pd.DataFrame({"About these results": lines})


def _data_sources_df() -> pd.DataFrame:
    rows = [
        ("U.S. Census ACS 2019-2023", "Block-group counts: age/sex, race, Hispanic, "
         "vehicles (B25044), household size (B11016), income — 34 Altadena block groups",
         "Who lives where; who has a car"),
        ("ACS PUMS 2023", "Anonymous example households, LA-area PUMAs 03724/03725",
         "Building realistic households"),
        ("Census TIGER/Line 2023", "Place + block-group boundaries",
         "Selecting Altadena; placing homes in the right neighborhood"),
        ("OpenStreetMap", "Drivable roads, Altadena + 3 km buffer (3,766 nodes / "
         "9,972 edges)", "The road network"),
        ("INRIX", "NOT SUPPLIED", "Nothing used; no traffic calibration"),
    ]
    return pd.DataFrame(rows, columns=["Source", "What / geography", "Used for"])


def _scenario_results_df() -> pd.DataFrame | None:
    idx_path = project_path("outputs", "ui", "index.json")
    if not idx_path.exists():
        return None
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    rows = []
    ui = project_path("outputs", "ui")
    for entry in index.values():
        f = ui / entry["file"]
        label = entry.get("label", entry.get("id"))
        try:
            meta = json.loads(f.read_text(encoding="utf-8")).get("meta", {})
        except Exception:  # noqa: BLE001
            meta = {}
        summ = meta.get("summary", {})
        row = {"scenario": label,
               "population": meta.get("population_source", ""),
               "policy": meta.get("policy", ""),
               "fleet_size": meta.get("fleet", "")}
        row.update(summ)
        rows.append(row)
    return pd.DataFrame(rows) if rows else None


def _population_fit_df() -> pd.DataFrame | None:
    p = project_path("data", "processed", "population_fit_report.json")
    if not p.exists():
        return None
    rep = json.loads(p.read_text(encoding="utf-8"))
    pbg = rep.get("per_block_group_fit", {})
    rows = [{"block_group": g, "fit_error_srmse": v.get("srmse"),
             "total_abs_error": v.get("tae"), "unsupported_combos": v.get("n_unsupported")}
            for g, v in pbg.items()]
    df = pd.DataFrame(rows)
    return df if len(df) else None


def _safe_sheet(name: str) -> str:
    bad = '[]:*?/\\'
    for c in bad:
        name = name.replace(c, " ")
    return name[:31]


def _autowidth(xw):
    for ws in xw.book.worksheets:
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 12), 60)


def main():
    out = project_path("outputs", "altadena_results.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)

    comparison_csvs = {
        "Policy cmp (real roads)": project_path("outputs", "compare_altadena",
                                                "policy_comparison_altadena.csv"),
        "Policy cmp (toy)": project_path("outputs", "compare_toy", "policy_comparison.csv"),
        "Demo comparison": project_path("outputs", "demo", "demo_comparison.csv"),
    }

    wrote = []
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        _readme_df().to_excel(xw, sheet_name="READ ME", index=False)
        wrote.append("READ ME")

        sr = _scenario_results_df()
        if sr is not None:
            sr.to_excel(xw, sheet_name="Scenario results", index=False)
            wrote.append("Scenario results")

        for name, path in comparison_csvs.items():
            if path.exists():
                pd.read_csv(path).to_excel(xw, sheet_name=_safe_sheet(name), index=False)
                wrote.append(name)

        pf = _population_fit_df()
        if pf is not None:
            pf.to_excel(xw, sheet_name="Population fit", index=False)
            wrote.append("Population fit")

        _data_sources_df().to_excel(xw, sheet_name="Data sources", index=False)
        wrote.append("Data sources")

        _autowidth(xw)

    print(f"wrote {out}")
    print("sheets:", ", ".join(wrote))


if __name__ == "__main__":
    main()
