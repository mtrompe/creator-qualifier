"""Human labelling: build a sheet of creators for Maxime to score, then import it back.

    python -m qualifier.labels make     # -> data/labels_to_fill.xlsx (100 creators)
    python -m qualifier.labels import   # reads the filled sheet into the `labels` table
"""
import sys
from pathlib import Path

import pandas as pd

from .db import connect

SHEET = Path(__file__).resolve().parents[2] / "data" / "labels_to_fill.xlsx"
N = 100

INSTRUCTIONS = (
    "fit_score: 1 = no fit for RingOut, 2 = weak, 3 = maybe, 4 = good, 5 = perfect fit. "
    "Judge the channel (open the link), not the outreach result. Add a short comment if useful."
)


def make() -> None:
    con = connect()
    df = pd.read_sql("SELECT id, name, platform, channel_url, audience_note, outreach_priority, replied "
                     "FROM creators WHERE channel_url LIKE 'http%'", con)
    # Stratified sample: every creator who replied, then an even spread across platforms and priorities
    replied = df[df.replied == 1]
    rest = df[df.replied == 0].sample(frac=1, random_state=42)
    groups = [g for _, g in rest.groupby(["platform", "outreach_priority"])]
    picked, i = [], 0
    while len(replied) + len(picked) < N and any(i < len(g) for g in groups):
        for g in groups:
            if i < len(g) and len(replied) + len(picked) < N:
                picked.append(g.iloc[i])
        i += 1
    out = pd.concat([replied, pd.DataFrame(picked)]).sample(frac=1, random_state=7)  # shuffle: hide the strata
    out = out[["id", "name", "platform", "channel_url", "audience_note"]]
    out["fit_score"] = ""
    out["comment"] = ""
    with pd.ExcelWriter(SHEET) as xw:
        out.to_excel(xw, sheet_name="labels", index=False)
        pd.DataFrame({"instructions": [INSTRUCTIONS]}).to_excel(xw, sheet_name="README", index=False)
    print(f"{len(out)} creators written to {SHEET}")


def import_() -> None:
    df = pd.read_excel(SHEET, sheet_name="labels")
    df = df[pd.to_numeric(df["fit_score"], errors="coerce").between(1, 5)]
    con = connect()
    with con:
        for _, r in df.iterrows():
            con.execute(
                "INSERT OR REPLACE INTO labels (creator_id, fit_score, comment) VALUES (?, ?, ?)",
                (int(r["id"]), int(r["fit_score"]), None if pd.isna(r["comment"]) else str(r["comment"])))
    print(f"{len(df)} labels imported")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"make": make, "import": import_}.get(cmd, lambda: sys.exit("usage: python -m qualifier.labels make|import"))()
