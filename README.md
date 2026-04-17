# Job Application AI Bot

Automates your entire job search: scrapes postings → scores matches → tailors your resume → auto-fills applications in Chrome → sends cold outreach → tracks everything in Excel.

---

## How It Works

```
Daily run:
  1. Scrape jobs from Indeed, LinkedIn, Glassdoor
  2. Score each job 0-100 against your profile using Claude AI
  3. Show you top matches — you approve each one (Y/N)
  4. For approved jobs:
     - Tailor your LaTeX resume to the job (content only, formatting untouched)
     - Compile to PDF via tectonic
     - Generate a personalized cover letter
     - Open application in Chrome, auto-fill every field it knows
     - Prompt you for anything it doesn't know (and remember your answer)
     - Find hiring manager via Hunter.io → send cold email with resume attached
  5. Log everything to tracking.xlsx
  6. Save anything it couldn't automate to data/pending_outreach/ for manual action
```

---

## What You Need to Provide

### 1. Your LaTeX Resume

Copy your Overleaf `.tex` source and any custom class files to `data/`:
```
data/master_resume.tex
data/format.cls          ← include if your resume uses a custom .cls file
```
The bot NEVER modifies these files. It copies them per job before compiling.

---

### 2. User Profile (`config/user_profile.yaml`)

```bash
cp config/user_profile.yaml.example config/user_profile.yaml
```

Open `config/user_profile.yaml` and fill in every field:

| Section | Required Fields |
|---|---|
| `personal` | full_name, email, phone, address, linkedin_url |
| `visa` | status, requires_sponsorship, authorized_to_work |
| `employment` | currently_employed, notice_period_days |
| `target` | roles, seniority, job_type, locations, remote_preference |
| `skills` | primary (list), years_experience |
| `skills.education` | degree, school, graduation_year |
| `outreach` | cold_email_tone, email_signature |

Optional but recommended:
- `personal.github_url`, `personal.portfolio_url`
- `visa.work_auth_expiry` (if OPT/H1B)
- `target.salary_min` (private, for matching only)
- `target.desired_salary` (what goes on application forms)
- `target.industries_preferred` / `industries_excluded`
- `eeo.*` (disability, veteran, race — all default to "prefer_not_to_say")
- `learned_answers` — pre-fill or let the bot learn these during runs:
  - `driver_license: true/false`
  - `how_did_you_hear: "LinkedIn"`

---

### 3. Scraper Config (`config/scraper_config.yaml`)

```bash
cp config/scraper_config.yaml.example config/scraper_config.yaml
```

Enable/disable job boards and set rate limits. LinkedIn is disabled by default (ToS risk).

---

### 4. Environment Variables (`.env`)

```bash
cp .env.example .env
```

Fill in:

| Variable | Where to get it | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | Yes |
| `SMTP_USER` | Your Gmail address | Yes |
| `SMTP_PASSWORD` | Gmail → Manage Account → Security → App Passwords | Yes |
| `HUNTER_IO_API_KEY` | hunter.io/api | Yes (for contact finding) |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | Your LinkedIn credentials | No |
| `SERPAPI_KEY` | serpapi.com | No (for Google Jobs) |

**Gmail App Password setup:**
1. Enable 2FA on your Google account
2. Go to myaccount.google.com → Security → App Passwords
3. Create a password for "Mail" → copy into `SMTP_PASSWORD`

---

## Setup

### Prerequisites

**Python 3.11+**
```bash
python --version  # must be 3.11+
```

**tectonic** (LaTeX compiler — downloads packages automatically, no TeX installation needed)

check installation here: https://tectonic-typesetting.github.io/book/latest/installation/

**Chrome** (must be installed — Playwright uses your real Chrome for applications)

### Install

```bash
git clone https://github.com/yourusername/job_bot
cd job_bot

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
playwright install chromium
```

### Configure

```bash
cp .env.example .env
cp config/user_profile.yaml.example config/user_profile.yaml
cp config/scraper_config.yaml.example config/scraper_config.yaml

# Edit all three files with your information
# Then copy your Overleaf .tex to:
# data/master_resume.tex
```

---

## Running

**Always dry-run first** to verify config before going live:

```bash
python -m src.pipeline.orchestrator --dry-run
```

This scrapes, scores, and prints what it would do — no emails sent, no applications submitted, no files written.

**Live run:**

```bash
python -m src.pipeline.orchestrator
```

---

## Daily Automation (Windows Task Scheduler)

1. Open Task Scheduler → Create Basic Task
2. Name: "Job Bot Daily"
3. Trigger: Daily, your preferred time (e.g. 8:00 AM)
4. Action: Start a Program
   - Program: `C:\path\to\job_bot\.venv\Scripts\python.exe`
   - Arguments: `-m src.pipeline.orchestrator`
   - Start in: `C:\path\to\job_bot`
5. Finish

---

## Project Structure

```
job_bot/
├── data/
│   ├── master_resume.tex        ← YOUR RESUME (gitignored, never modified)
│   ├── resumes/                 ← Tailored PDFs: Name_Company_resume.pdf
│   ├── cover_letters/           ← Generated cover letters
│   ├── tracking.xlsx            ← All 12-column tracking database
│   ├── seen_jobs.json           ← Dedup store (prevents re-processing)
│   └── pending_outreach/        ← Outreach drafts needing manual send
│
├── config/
│   ├── user_profile.yaml        ← YOUR PROFILE (gitignored)
│   └── scraper_config.yaml      ← Job board settings
│
├── src/
│   ├── pipeline/
│   │   ├── orchestrator.py      ← Daily pipeline entrypoint
│   │   ├── scraper.py           ← Aggregates all job board scrapers
│   │   ├── matcher.py           ← Claude-based job scoring (0-100)
│   │   ├── resume_tailor.py     ← .tex modification + tectonic compile
│   │   ├── cover_letter.py      ← Claude cover letter generation
│   │   ├── applicator.py        ← Playwright Chrome form automation
│   │   ├── form_learner.py      ← Unknown field prompting + learning
│   │   ├── contact_finder.py    ← Hunter.io + LinkedIn fallback
│   │   └── outreach.py          ← Cold email generation + sending
│   ├── scrapers/
│   │   ├── indeed.py
│   │   ├── glassdoor.py
│   │   └── linkedin.py
│   ├── ats/
│   │   └── detector.py          ← Fingerprints ATS from URL
│   ├── tracking/
│   │   ├── tracker.py           ← Excel read/write
│   │   └── deduplication.py     ← SHA-256 job hash store
│   └── utils/
│       ├── claude_client.py     ← Anthropic API wrapper
│       ├── config_loader.py     ← YAML + .env loading + validation
│       ├── email_sender.py      ← Gmail SMTP sender
│       └── latex_compiler.py    ← tectonic wrapper
```

---

## Tracking Database (tracking.xlsx)

| Column | Description |
|---|---|
| Company Name | |
| Job Posting URL | |
| Job Description | Role, location, first 500 chars of JD |
| Match Score | "85 — Strong Python/ML match" |
| Tailored Resume | Y / N |
| Application Submitted | Y / N |
| Application Link | URL where application was submitted |
| Date Applied | |
| Hiring Manager Found | Y / NA |
| Contact Info | Email or LinkedIn URL |
| Cold Outreach URL | LinkedIn search URL used |
| Outreach Status | sent / reply received / ghosted / in talks / referral received |
| Company Response | applied / rejected / interviewing / offer / not a match / no news / not hiring / pending user input |

---

## Pending User Input

Anything the bot couldn't fully automate lands in `data/pending_outreach/` and is marked **"pending user input"** in the tracker. Each file contains:
- Recipient email (or LinkedIn search URL if email not found)
- Contact name and title
- Subject line
- Email body (ready to send)
- Resume path to attach

Open the file, copy-paste into your email client, attach the resume, and send.

---

## Cloning for Your Own Use

This project is fully portable. To use it for your own job search:

1. Clone the repo
2. Follow the Setup steps above
3. Fill in `config/user_profile.yaml` with your information
4. Add your Overleaf `.tex` to `data/master_resume.tex`
5. Run `--dry-run` first

No code changes needed — everything is driven by config.
