# job-agent

Local job-search pipeline: scrape → filter → score (LLM) → cover letter → human review.
Runs entirely on your machine: Python + SQLite + Ollama.

## Setup (Pop!_OS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull gpt-oss:20b        # or nemotron-cascade-2, gemma3:12b — see config.yaml
```

## Usage

```bash
python run.py fetch    # scrape sources, filter, store in jobs.db
python run.py list     # show pipeline state by status
```

Edit `config.yaml`: search terms, sites, thresholds, and — most importantly —
the `cv:` block, which is the ONLY source of truth the LLM may use in letters.

## Pipeline states

new → scored → letter_drafted → approved/rejected → applied
(`filtered_out` = killed by rule-based filters before any LLM call)

## Roadmap

- [x] v1: ingestion (jobspy) + rule filters + SQLite
- [ ] v2: LLM scoring (`pipeline/score.py`, uses `llm/client.chat_structured` + MatchResult)
- [ ] v3: cover letter generation + fact-check pass against cv block
- [ ] v4: review UI (or stay in terminal, honestly fine)
- [ ] cron: daily `run.py fetch`

## Design rules

1. Idempotent: re-runs never duplicate or reset status (INSERT OR IGNORE).
2. One failing source never kills the run.
3. No LLM call before rule filters.
4. Nothing ever auto-submits. Ever.
