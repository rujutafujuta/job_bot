# Job Bot — Private, Local Job Application Pipeline

Discovers jobs daily from 8+ sources, filters them with two-stage AI scoring, generates deep evaluation reports, tailors your resume, and prepares all application materials — before you open the app. You review, decide, and act. The bot never submits, sends, or applies on your behalf.

**AI layer:** Claude Code CLI (subprocess). No Anthropic API key. One billing location.

---

## How It Works

```
Daily run (3am, unattended):
  1. Read cv.md → determine target roles (one-time + on CV change)
  2. Scrape jobs from 8 sources (Apify + free APIs)
  3. Deduplicate: SHA-256 of normalized title+company
  4. Stage 1 fast scoring (Claude, <10s/job):
       score < 70   → hash stored, never seen again
       score 70–94  → tracked, shown in Scored tab
       score 95+    → triggers Stage 2 automatically
  5. Stage 2 deep evaluation (Claude + WebSearch):
       6-block report: role summary, CV match, level strategy,
       comp research, personalization plan, interview prep
       + posting legitimacy check
  6. Tailored resume generated per job (cv.md → .md → PDF)
  7. Cover letter generated per job
  8. URL liveness check on all unacted jobs
  9. Dashboard updated — user reviews in the morning
```

**Human gates (non-negotiable):**
- Bot never clicks Submit — user always submits the application
- Bot never sends emails or messages — user always sends manually
- Bot never changes numbers in your resume — years, %, $, dates frozen

---

## What You Need to Provide

### 1. Your Master CV (`data/cv.md`)

A comprehensive Markdown document of everything you've ever done — every project, internship, certification, publication, skill, and metric. Not formatted for any specific job. Claude selects and tailors subsets per application.

```
data/cv.md      ← YOUR CV (gitignored, source of truth)
```

### 2. User Profile (`config/user_profile.yaml`)

```bash
cp config/user_profile.yaml.example config/user_profile.yaml
```

Or run the onboarding wizard on first launch — it generates this file interactively.

| Section | Fields |
|---|---|
| `personal` | name, email, phone, city, linkedin_url, github_url |
| `work_auth` | visa type, expiry date (if applicable) |
| `preferences` | job types, remote preference, target locations, salary floor |
| `education` | degree, field, university, graduation year |
| `cover_letter_context` | career goals, motivations, strengths, industries |
| `exclusions` | companies and industries to skip |
| `learned_answers` | auto-populated by form-fill co-pilot over time |

### 3. Environment Variables (`.env`)

```bash
cp .env.example .env
```

| Variable | Where to get it | Required |
|---|---|---|
| `APIFY_API_TOKEN` | apify.com → Settings → API | For LinkedIn/Indeed/Glassdoor/Google Jobs/ZipRecruiter |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | developer.adzuna.com | For Adzuna source |

**No `ANTHROPIC_API_KEY` needed.** All AI runs through your Claude Code subscription via the `claude` CLI.

---

## Prerequisites

**Python 3.11+**
```bash
python --version
```

**Claude Code CLI** (must be installed and authenticated)
```bash
claude --version
```

**Playwright**
```bash
playwright install chromium
```

---

## Setup

```bash
git clone https://github.com/yourusername/job_bot
cd job_bot

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
playwright install chromium
```

Copy and fill config files:

```bash
cp .env.example .env
cp config/user_profile.yaml.example config/user_profile.yaml
# Edit both files, then add your master CV:
# data/cv.md
```

**First run — onboarding wizard:**

```bash
python -m src.setup.onboarding
```

This walks you through your profile, sets up Windows Task Scheduler for 3am daily runs, and triggers role detection from your CV.

---

## Running

**Start the web app:**
```bash
uvicorn src.web.app:app --reload
# Open http://localhost:8000
```

**Run the pipeline manually:**
```bash
# Full scrape + score + evaluate pipeline
python -m src.pipeline.orchestrator --phase scrape

# Dry run (scrapes and scores, writes nothing)
python -m src.pipeline.orchestrator --phase scrape --dry-run

# Trigger Stage 2 deep evaluation on a specific job
python -m src.pipeline.orchestrator --phase prepare <job_id>

# Launch Playwright form-fill for a specific job
python -m src.pipeline.orchestrator --phase apply <job_id>
```

---

## Dashboard

**Dashboard (`/`)** — Today's stats, priority job queue, follow-up reminders, Run Now button, activity feed.

**Review (`/review`)**
- *Ready to Apply* — Jobs scoring 95+, full evaluation done, tailored resume + cover letter generated. One click to open pre-filled application.
- *Scored* — Jobs scoring 70–94. Read Stage 1 summary, click Prepare to run full evaluation.

**Applied (`/applied`)** — All post-application tracking. Inline status editor, follow-up dates, links to resume/cover letter PDFs, Excel export.

**Outreach (`/outreach`)** — Pending email + LinkedIn message drafts. Send or copy to clipboard — never auto-sent.

**Settings (`/settings`)** — CV editor, role list viewer + regenerate, user profile editor, contact manager, scraper toggles, scheduling config.

---

## Priority Score

Jobs are sorted by a computed priority score visible in the Review and Dashboard queues:

| Factor | Points |
|---|---|
| Deadline <3 days away | +30 |
| Referral contact at company | +25 |
| Deadline <7 days away | +20 |
| Fit score (proportional) | up to +20 |
| Job posted <7 days ago | +10 |
| Positive company health signals | +8 |
| Salary above minimum (proportional) | up to +8 |
| In queue 5+ days untouched | +7 |
| Negative signals (layoffs, etc.) | −15 |
| Job posted >30 days ago | −5 |

---

## Project Structure

```
job_bot/
├── data/
│   ├── cv.md                       ← YOUR MASTER CV (gitignored)
│   ├── tracking.db                 ← SQLite database (gitignored)
│   ├── reports/                    ← Stage 2 evaluation reports (.md)
│   ├── resumes/                    ← Tailored resumes per job (.md + .pdf)
│   ├── cover_letters/              ← Cover letters per job (.md)
│   └── pending_outreach/           ← Email + LinkedIn drafts
│
├── config/
│   ├── user_profile.yaml           ← YOUR PROFILE (gitignored)
│   ├── user_profile.yaml.example   ← Template
│   └── target_roles.yaml           ← Auto-generated from cv.md (gitignored)
│
├── src/
│   ├── pipeline/
│   │   ├── orchestrator.py         ← Pipeline entrypoint (--phase scrape/prepare/apply)
│   │   ├── role_detector.py        ← cv.md → target_roles.yaml via Claude
│   │   ├── stage1_scorer.py        ← Fast score 0-100 via Claude subprocess
│   │   ├── stage2_evaluator.py     ← 6-block deep report (Claude + WebSearch)
│   │   ├── resume_tailor.py        ← cv.md → tailored .md per job
│   │   ├── cover_letter.py         ← Cover letter generation
│   │   ├── applicator.py           ← Playwright form-fill co-pilot
│   │   ├── form_learner.py         ← Learns field answers across applications
│   │   ├── contact_finder.py       ← Recruiter/HM finding via Claude WebSearch
│   │   └── outreach.py             ← Email + LinkedIn draft generation
│   ├── scrapers/
│   │   ├── base.py                 ← Scraper base class
│   │   ├── apify_adapter.py        ← Apify job-board-scraper actor
│   │   ├── himalayas.py
│   │   ├── remotive.py
│   │   ├── remoteok.py
│   │   ├── simplify.py
│   │   ├── adzuna.py
│   │   └── jobicy.py
│   ├── tracking/
│   │   ├── db.py                   ← SQLite schema + all DB operations
│   │   └── deduplication.py        ← SHA-256 dedup against both tables
│   ├── ats/
│   │   └── detector.py             ← ATS fingerprint from URL
│   ├── web/
│   │   ├── app.py                  ← FastAPI app + all routes
│   │   └── templates/              ← Jinja2 HTML templates
│   ├── setup/
│   │   ├── onboarding.py           ← First-run wizard
│   │   └── profile_wizard.py       ← Interactive profile builder
│   └── utils/
│       ├── claude_runner.py        ← Claude Code CLI subprocess wrapper
│       ├── config_loader.py        ← YAML + .env loading + validation
│       └── email_sender.py         ← Gmail SMTP sender
│
└── tests/                          ← pytest test suite
```

---

## Scoring System

**Stage 1** (fast, no web search, <10s/job):
- Claude reads job description + profile summary
- Returns score 0–100 + 2-line reasoning
- `<70` → hash stored in `discarded_hashes`, never re-processed
- `70–94` → full record stored, shown in Scored tab
- `95+` → full record + triggers Stage 2

**Stage 2** (deep, WebSearch + WebFetch, ~2min/job):
Claude generates a 3,000–5,000 word evaluation across 6 blocks:
- **Block A** — Role summary, company overview, team context, posting freshness
- **Block B** — CV match, gap analysis with mitigation strategies, company health signals
- **Block C** — Level strategy, seniority realism, archetype (startup / big tech / enterprise)
- **Block D** — Live comp research (Glassdoor, Levels.fyi, Blind via WebSearch)
- **Block E** — Personalization plan: top 5 resume changes + cover letter hooks
- **Block F** — Interview prep: likely technical topics, behavioral questions, red flags
- **Legitimacy check** — Is this a real posting? Ghost posting signals flagged inline.

Claude uses only verifiable information. Gaps are flagged explicitly, not fabricated.

---

## Status Values

```
new → scored → ready → applied → phone_screen → technical → offer → negotiating → accepted
                                                                                 → withdrawn
                    → skipped
                    → discarded
                                → rejected
                                → ghosted
```

Ghosted auto-triggers 30 days after `applied_date` if status hasn't changed.

---

## Cloning for Your Own Use

This system is fully generic — no hardcoded assumptions about role type, industry, location, or skill set. Everything is driven by your `cv.md` and `user_profile.yaml`.

1. Clone the repo
2. Run `python -m src.setup.onboarding`
3. Add your `data/cv.md`
4. Run `python -m src.pipeline.orchestrator --phase scrape --dry-run`
5. Open `http://localhost:8000` and review

## References : 
This project is a mix of my own job_bot logic and https://github.com/santifer/career-ops. I have added/ changed career-ops' logic to fit my use cases. Feel free to contribute, or change my code as per your needs. 

## License

MIT