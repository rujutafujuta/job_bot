# Job Bot — Private, Local Job Application Pipeline

Discovers jobs daily from 8+ sources, filters them with two-stage AI scoring, generates deep evaluation reports, tailors your resume, and prepares all application materials — before you open the app. You review, decide, and act. The bot never submits, sends, or applies on your behalf.

**AI layer:** Claude Code CLI (subprocess). No Anthropic API key. One billing location (claude code subscription)

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

## Getting Started

### 1. Clone and install

```bash
git clone https://github.com/rujutafujuta/job_bot
cd job_bot

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create a desktop shortcut

Run this once — it creates a **Job Bot** shortcut on your desktop:

```bash
python scripts/create_shortcut.py
```

From here, you never need to open a terminal again. Double-click **Job Bot** any time to launch.

<details>
<summary>Manual shortcut (if the script doesn't work)</summary>

1. Right-click your desktop → **New → Shortcut**
2. In the "Type the location of the item" box, paste this (with your actual paths):
   ```
   C:\Users\YourName\projects\job_bot\.venv\Scripts\pythonw.exe C:\Users\YourName\projects\job_bot\launch.py
   ```
   Not sure of the paths? Run this in your terminal to print the exact `pythonw.exe` path:
   ```bash
   python -c "import sys; print(sys.executable.replace('python.exe','pythonw.exe'))"
   ```
3. Click **Next**, name it **Job Bot**, click **Finish**

</details>

### 3. Launch the app

Double-click the **Job Bot** shortcut (or run `python launch.py` from the terminal).

**First run:** A setup GUI walks you through everything:
- Checks Python 3.11+, Claude Code CLI, and Playwright — and alerts you to anything missing
- Asks for your API credentials:

| Variable | Where to get it | Required |
|---|---|---|
| `APIFY_TOKEN` | apify.com → Settings → API Tokens | Yes — covers LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter |
| `ADZUNA_APP_ID` / `ADZUNA_API_KEY` | developer.adzuna.com | Optional — adds Adzuna source |

- Opens a terminal for the profile setup wizard — follow the prompts to create your profile and CV
- Starts the dashboard automatically when done

**Every subsequent launch:** Server starts silently, browser opens, a small status window lets you stop when done.

> **One thing the launcher can't install for you:** [Claude Code CLI](https://claude.ai/code). All AI features run through it — no `ANTHROPIC_API_KEY` needed, just your Claude subscription. Install and authenticate it once before first launch.

### 4. Run your first scrape

Click **Run Pipeline** on the dashboard, or run it from the terminal:

```bash
python -m src.pipeline.orchestrator --phase scrape
```

This scrapes all enabled sources, scores every posting, and automatically triggers deep evaluation + resume tailoring for your best matches (95+ score). Takes a few minutes on first run.

### 5. Schedule daily runs

By default, the **First-time setup** will ask if you want to schedule daily runs. The pipeline is designed to run automatically (typically at 3:00 AM) while you sleep, so your dashboard is ready when you wake up.

**To change or manually set the schedule:**
If you skipped this during setup or want to change the time, run:
```bash
python -m src.pipeline.orchestrator --schedule

To verify it was registered:
```bash
schtasks /Query /TN "JobBot Scrape"
```

To remove it:
```bash
schtasks /Delete /TN "JobBot Scrape" /F
```

---

## What You Need to Provide

### Master CV (`data/cv.md`)

A comprehensive Markdown document of everything you've ever done — every project, internship, certification, publication, skill, and metric. Not formatted for any specific job. Claude selects and tailors subsets per application.

The first-run setup wizard asks you to paste or write your CV interactively. After that, if you update your CV, go to **Settings → CV Editor** in the dashboard to edit it directly in the browser — no need to touch the file manually.

### User Profile (`config/user_profile.yaml`)

Created automatically during the first-run setup wizard — you won't need to write it by hand. To update it after setup, go to **Settings → Profile** in the dashboard.

| Section | Fields |
|---|---|
| `personal` | name, email, phone, city, linkedin_url, github_url |
| `work_auth` | visa type, expiry date (if applicable) |
| `preferences` | job types, remote preference, target locations, salary floor |
| `education` | degree, field, university, graduation year |
| `cover_letter_context` | career goals, motivations, strengths, industries |
| `exclusions` | companies and industries to skip |
| `outreach` | max emails per company, tone |
| `learned_answers` | auto-populated by the Apply Co-Pilot over time |

---

## Daily Workflow

The 3am scheduled run handles everything before you wake up. Your morning routine is just review and act:

1. **Double-click Job Bot** — dashboard opens at http://localhost:8000
2. **Review queue** — Read the Stage 2 report for each ready job. Check the tailored resume and cover letter
3. **Apply** — Click Apply. Playwright opens the form pre-filled — you review and click Submit yourself
4. **Outreach** — Go to `/outreach`. Copy the drafted email or LinkedIn message and send it manually
5. **Track** — Update statuses in `/applied` as you hear back. Follow-up reminders appear automatically
6. **Close Job Bot** — click Stop in the status window when you're done for the day

---

## Pages

**Dashboard (`/`)** — Today's stats, priority job queue, follow-up reminders, Run Pipeline button, activity feed. Alerts if any scraper source has been returning 0 jobs for 3+ days.

**Review (`/review`)**
- *Ready to Apply* — Jobs scoring 95+. Full evaluation, tailored resume, and cover letter generated. One click to open pre-filled Playwright browser.
- *Scored* — Jobs scoring 70–94. Read the Stage 1 summary. Click Prepare to trigger full evaluation.

**Applied (`/applied`)** — All post-application tracking. Inline status editor, follow-up dates, links to resume/cover letter PDFs, Excel export.

**Outreach (`/outreach`)** — Email and LinkedIn message drafts. Status badges (draft / sent / replied). Copy to clipboard or mark as sent/replied — never auto-sent.

**Settings (`/settings`)** — CV editor, role list viewer + regenerate, user profile editor, contact manager (LinkedIn CSV import), scraper toggles, scraper health table, backup/restore.

---

## Backup and Restore

Create a zip backup of your database and all data files from the Settings page, or run it directly:

```bash
# Creates backups/job_bot_backup_YYYY-MM-DD_HHMMSS.zip
# Contains data/tracking.db + all files in data/
```

Restore by uploading a backup zip from the Settings page. The server must be restarted after restore.

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

## Scoring System

**Stage 1** (fast, no web search, <10s/job):
- Claude reads job description + profile summary
- Returns score 0–100 + 2-line reasoning
- `<70` → hash stored in `discarded_hashes`, never re-processed
- `70–94` → full record stored, shown in Scored tab
- `95+` → full record + triggers Stage 2 automatically

**Stage 2** (deep, WebSearch + WebFetch, ~2min/job):
Claude generates a 3,000–5,000 word evaluation across 6 blocks:
- **Block A** — Role summary, company overview, team context, posting freshness
- **Block B** — CV match, gap analysis with mitigation strategies, company health signals, referral contacts
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

## Running the Pipeline Manually

```bash
# Full scrape + score + evaluate pipeline
python -m src.pipeline.orchestrator --phase scrape

# Dry run (scrapes and scores, writes nothing to DB)
python -m src.pipeline.orchestrator --phase scrape --dry-run

# Trigger Stage 2 deep evaluation on a specific job
python -m src.pipeline.orchestrator --phase prepare --job-id <id>

# Launch Playwright form-fill for a specific job
python -m src.pipeline.orchestrator --phase apply --job-id <id>

# Register daily 3am scheduled task (Windows Task Scheduler)
python -m src.pipeline.orchestrator --schedule
```

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
│   ├── logs/                       ← Integrity check logs
│   └── pending_outreach/           ← Legacy .txt drafts (migrated to DB on startup)
│
├── backups/                        ← Backup zips (gitignored)
│
├── config/
│   ├── user_profile.yaml           ← YOUR PROFILE (gitignored)
│   ├── user_profile.yaml.example   ← Template
│   ├── settings.yaml               ← Scraper toggles + app settings
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
│   │   ├── outreach.py             ← Email + LinkedIn draft generation
│   │   ├── priority_scorer.py      ← Weighted priority score computation
│   │   ├── rejection_analyzer.py   ← Pattern analysis across rejected/ghosted jobs
│   │   └── integrity_checker.py    ← DB consistency checks (runs after every scrape)
│   ├── scrapers/
│   │   ├── base.py                 ← Scraper base class + JobPosting dataclass
│   │   ├── apify_adapter.py        ← Apify actor (LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter)
│   │   ├── himalayas.py
│   │   ├── remotive.py
│   │   ├── remoteok.py
│   │   ├── simplify.py
│   │   ├── adzuna.py
│   │   └── jobicy.py
│   ├── contacts/
│   │   └── importer.py             ← LinkedIn CSV contact import
│   ├── tracking/
│   │   ├── db.py                   ← SQLite schema + all DB operations
│   │   └── deduplication.py        ← SHA-256 + fuzzy dedup
│   ├── ats/
│   │   └── detector.py             ← ATS fingerprint from URL
│   ├── web/
│   │   ├── app.py                  ← FastAPI app + all routes
│   │   └── templates/              ← Jinja2 HTML templates
│   ├── setup/
│   │   ├── onboarding.py           ← First-run wizard
│   │   └── profile_wizard.py       ← Interactive profile builder
│   └── utils/
│       ├── backup.py               ← Backup/restore zip utility
│       ├── claude_runner.py        ← Claude Code CLI subprocess wrapper
│       ├── config_loader.py        ← YAML + .env loading + validation
│       └── scheduler.py            ← Windows Task Scheduler integration
│
├── launch.py                       ← One-click launcher (GUI setup + server start)
├── scripts/
│   └── create_shortcut.py          ← Creates a desktop shortcut for launch.py
└── tests/                          ← pytest test suite (354 tests)
```

---

## References

This project is a mix of my own job_bot logic and [career-ops by @santifer](https://github.com/santifer/career-ops). I have adapted career-ops' analysis logic to fit my use cases. Feel free to contribute or adapt as needed.

## License

MIT
