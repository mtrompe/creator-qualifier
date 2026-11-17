"""Import creators from the RingOut outreach spreadsheet into SQLite."""
import re
import sys
from pathlib import Path

import pandas as pd

from .db import connect

REPLIED = re.compile(r"A répondu|répondu le|Placement", re.IGNORECASE)


def import_sheet(xlsx: Path) -> int:
    df = pd.read_excel(xlsx, sheet_name="Streamers")
    df = df[df["Nom"].notna() & df["Lien chaîne"].notna()]
    df = df[df["Plateforme"].isin(["YouTube", "Twitch"])]
    df = df[df["Lien chaîne"].astype(str).str.startswith("http")]  # skip notes like "(search X on YouTube)"

    con = connect()
    n = 0
    with con:
        for _, r in df.iterrows():
            status = str(r.get("Statut") or "")
            con.execute(
                """INSERT INTO creators (name, platform, channel_url, audience_note,
                                         outreach_priority, contacted, replied)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(channel_url) DO UPDATE SET
                     audience_note=excluded.audience_note,
                     outreach_priority=excluded.outreach_priority,
                     contacted=excluded.contacted,
                     replied=excluded.replied""",
                (
                    str(r["Nom"]).strip(),
                    r["Plateforme"],
                    str(r["Lien chaîne"]).strip(),
                    None if pd.isna(r.get("Audience / Taille")) else str(r["Audience / Taille"]),
                    None if pd.isna(r.get("Priorité")) else str(r["Priorité"]),
                    1 if str(r.get("Contacté ?")) == "Oui" else 0,
                    1 if REPLIED.search(status) else 0,
                ),
            )
            n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m qualifier.ingest <outreach.xlsx>")
    print(f"{import_sheet(Path(sys.argv[1]))} creators imported")
