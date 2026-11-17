"""Compare LLM scores with Maxime's hand labels, per model and prompt version.

    python -m qualifier.evaluate

Metrics (on the hand-labelled creators):
- exact      : share of creators where the model gives exactly the same score
- within_1   : share where the model is at most 1 point away
- mae        : mean absolute error, in points
- spearman   : rank correlation (does the model order creators the same way?)
- precision / recall on the decision that matters: "contact" = score >= 4
- latency and tokens per creator; failures
"""
import pandas as pd

from .db import connect

CONTACT = 4


def evaluate() -> pd.DataFrame:
    con = connect()
    runs = pd.read_sql("""
        SELECT r.model, r.prompt_version, r.creator_id, r.fit_score AS pred, r.latency_ms,
               r.input_tokens, r.output_tokens, r.error, l.fit_score AS truth
        FROM llm_runs r JOIN labels l ON l.creator_id = r.creator_id
        WHERE r.id IN (SELECT MAX(id) FROM llm_runs GROUP BY creator_id, model, prompt_version)""", con)
    if runs.empty:
        raise SystemExit("no scored, labelled creators yet: run qualifier.labels import, then qualifier.classify")
    out = []
    for (model, prompt), g in runs.groupby(["model", "prompt_version"]):
        ok = g[g.error.isna()]
        err = (ok.pred - ok.truth).abs()
        tp = ((ok.pred >= CONTACT) & (ok.truth >= CONTACT)).sum()
        out.append({
            "model": model, "prompt": prompt, "n": len(ok), "failures": len(g) - len(ok),
            "exact": round((err == 0).mean(), 2),
            "within_1": round((err <= 1).mean(), 2),
            "mae": round(err.mean(), 2),
            "spearman": round(ok.pred.rank().corr(ok.truth.rank()), 2),  # Spearman = Pearson on ranks (no scipy needed)
            "precision@4": round(tp / max(1, (ok.pred >= CONTACT).sum()), 2),
            "recall@4": round(tp / max(1, (ok.truth >= CONTACT).sum()), 2),
            "latency_s": round(ok.latency_ms.mean() / 1000, 1),
            "tokens_in": int(ok.input_tokens.mean()),
            "tokens_out": int(ok.output_tokens.mean()),
        })
    return pd.DataFrame(out).sort_values("mae")


if __name__ == "__main__":
    print(evaluate().to_markdown(index=False))
