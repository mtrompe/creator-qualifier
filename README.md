# Creator Qualifier

An LLM pipeline that decides which YouTube / Twitch creators are worth contacting to promote
**RingOut**, an online multiplayer PvP third-person arena shooter I am building solo
([Steam page](https://store.steampowered.com/app/5020730/RingOut/)).

During my outreach campaign I researched ~1,000 creators and sent ~900 personalised emails.
Deciding who is a good fit was the slow, manual part. This project automates that decision
and, above all, **measures how well the model agrees with my own judgement**, at what cost.

Full write-up of the iterations, results and lessons: [LESSONS_LEARNED.txt](LESSONS_LEARNED.txt).

## Pipeline

```
outreach sheet ──> ingest ──> SQLite <── fetch (YouTube Data API v3, Twitch Helix)
                                 │
                                 ├──> classify (Mistral, structured JSON output)   [step 3]
                                 │
                   human labels ─┴──> evaluate (agreement, cost, latency)         [step 4]
```

| Step | Module | Status |
|---|---|---|
| 1. Import creators from the outreach sheet | `qualifier.ingest` | done |
| 2. Fetch channel data (titles, games, language, audience) | `qualifier.fetch` | done, needs API keys |
| 2b. Reference labels: 100 creators, LLM-assisted first pass reviewed by hand | `qualifier.labels` | done |
| 3. LLM classification with versioned prompts, run locally (Ollama + Mistral 7B) | `qualifier.classify` | done |
| 4. Evaluation: model vs. human, latency and tokens per model | `qualifier.evaluate` | done |
| 5. Iteration: label review showed inactivity drove many of my scores; added last-upload date and average views, prompt v2 | `fetch --refresh`, `--prompt v2` | done |

All data lives in `data/qualifier.db` (SQLite). Every LLM call is stored with its model,
prompt version, tokens and latency, so any result can be traced and compared.

## Setup (Windows, PowerShell)

```powershell
cd $HOME\Documents\creator-qualifier
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # then fill in the keys
cd src
python -m qualifier.ingest ..\data\outreach.xlsx
python -m qualifier.fetch --limit 20     # try a few channels first
python -m qualifier.fetch                # then everything
python -m qualifier.labels make          # -> data\labels_to_fill.xlsx
python -m qualifier.labels import        # once the sheet is filled in
ollama pull mistral
python -m qualifier.classify --model mistral --only-labeled
python -m qualifier.evaluate
```

## Reference labels

I labelled 100 creators (stratified sample) on a 1-5 fit scale. To save time, an LLM (Claude)
produced a first pass with a one-line justification per channel; I then reviewed every score
and corrected the ones I disagreed with. Disagreements are recorded in the `comment` column.

## Why a local model

The creator data includes personal contact details. Running Mistral 7B locally through Ollama
means no creator data leaves the machine, at zero marginal cost. The trade-off (speed and
accuracy vs. a larger cloud model) is exactly what `qualifier.evaluate` measures.

## Privacy

`data/` contains creators' contact details and is excluded from git. Only code and
aggregated results are published.
