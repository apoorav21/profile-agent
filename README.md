# Profile Agent

An automated personal branding agent that watches your GitHub profile and keeps everything else in sync — automatically.

Every time you push a new repository, the agent wakes up, analyzes the project, rewrites your resume, updates your GitHub profile README, and posts about it on LinkedIn. No manual steps, no copy-pasting bullet points, no forgetting to update your CV.

---

## The Problem It Solves

Developers build things constantly but rarely have the time (or remember) to:
- Update their resume with the new project
- Post about it on LinkedIn before the excitement fades
- Keep their GitHub profile README current
- Maintain a coherent narrative across all platforms over time

This agent handles all of that automatically, and because it reads the full history of your posts and projects before generating anything, every post sounds like *you* — not a template.

---

## How It Works

```
GitHub (new repo detected)
         │
         ▼
   repo_analyzer.py        ← Reads README, languages, topics, screenshots
         │
         ▼
   openai_brain.py         ← One GPT-4o call with full context:
         │                    all past projects, last 20 LinkedIn posts,
         │                    narrative arc, target roles
         │
         ├──► github_writer.py     → Updates apoorav21/apoorav21 profile README
         ├──► resume_writer.py     → GPT-4o edits LaTeX source → tectonic compiles PDF
         ├──► linkedin_writer.py   → Posts with project screenshots (if available)
         └──► twitter_writer.py    → Posts a punchy tweet (optional)
```

### Context Awareness

The agent keeps a SQLite database of every repo, every LinkedIn post, every tweet, and the current "narrative arc". Before generating any content, GPT-4o sees all of this — so posts never repeat the same angle, LinkedIn tones rotate, and the resume always reflects the strongest 4-5 projects from your full history.

### Resume Updates (1-page constraint)

The resume is maintained as a LaTeX source file. GPT-4o edits it surgically — updating the Projects section, Summary, and Skills — then `tectonic` compiles it to PDF. If adding a new project would push the resume over one page, the agent automatically drops the lowest-significance project. Every version is stored in SQLite so you can roll back any time.

### LinkedIn Posts (job-seeking mode)

Posts are structured to appeal to technical recruiters and hiring managers:
1. **Hook** — the specific problem being solved
2. **Tech choices** — *why* specific tools were used, not just *what*
3. **Architecture** — how components fit together
4. **Result** — concrete metric or outcome
5. **CTA** — signals open-to-work status

---

## Project Structure

```
├── orchestrator/main.py          ← Entry point (scheduled or manual)
├── monitors/github_monitor.py    ← Polls GitHub for new/updated repos
├── analyzers/repo_analyzer.py    ← Fetches README, languages, screenshots
├── brain/openai_brain.py         ← GPT-4o: generates all content at once
├── writers/
│   ├── github_writer.py          ← Updates profile README via GitHub API
│   ├── resume_writer.py          ← LaTeX edits + tectonic PDF compilation
│   ├── linkedin_writer.py        ← LinkedIn REST API v202503 posting
│   └── twitter_writer.py         ← Tweepy v4 posting (optional)
├── auth/
│   ├── linkedin_oauth.py         ← One-time OAuth flow
│   └── twitter_setup_check.py    ← Validates Twitter credentials
├── storage/db.py                 ← SQLite: repos, posts, resume versions, context
├── resume/resume_current.tex     ← LaTeX resume source (auto-maintained)
├── bootstrap.py                  ← One-time setup: seeds existing repos into DB
└── launchd/                      ← macOS scheduler (runs daily at 10am)
```

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install [tectonic](https://tectonic-typesetting.github.io) for LaTeX compilation:
```bash
brew install tectonic
```

### 2. Configure `.env`

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required:
- `OPENAI_API_KEY` — from [platform.openai.com](https://platform.openai.com)
- `GITHUB_TOKEN` — PAT with `repo` + `read:user` scopes
- `GITHUB_USERNAME` — your GitHub username

### 3. Set up LinkedIn OAuth (one-time)

Create a LinkedIn app at [developer.linkedin.com](https://developer.linkedin.com), enable the **Share on LinkedIn** product, set redirect URI to `http://127.0.0.1:8080/callback`, then run:

```bash
python auth/linkedin_oauth.py
```

This opens a browser, completes the OAuth flow, and writes tokens to `.env` automatically.

### 4. Bootstrap existing repos

Seeds your current GitHub repos into the database so they're not treated as "new" on first run:

```bash
python bootstrap.py
```

### 5. Add your resume

Place your resume as `resume/resume_current.tex` (LaTeX format). The agent will use this as the source of truth and update it going forward.

### 6. Install the daily scheduler (macOS)

```bash
cp launchd/com.apoorav.profileagent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.apoorav.profileagent.plist
```

Runs daily at 10am. Uses `StartCalendarInterval` so missed runs fire when your Mac wakes from sleep.

---

## Usage

**Automatic** — just push a new repo to GitHub. The agent runs daily and handles everything.

**Manual run for a specific repo:**
```bash
python orchestrator/main.py --repo REPO_NAME
```

**Dry run** (analyze only, no posting):
```bash
# Set in .env:
ENABLE_LINKEDIN_POSTING=false
ENABLE_RESUME_UPDATE=false
ENABLE_GITHUB_README_UPDATE=false
```

---

## Twitter/X Setup (optional)

Create a Twitter Developer app with Read+Write permissions, generate OAuth 1.0a tokens, add them to `.env`, then:
```bash
python auth/twitter_setup_check.py
# Set ENABLE_TWITTER_POSTING=true in .env
```

---

## Tech Stack

| Component | Technology |
|---|---|
| AI Brain | OpenAI GPT-4o (brain) + GPT-4o-mini (repo analysis) |
| Resume | LaTeX + [tectonic](https://tectonic-typesetting.github.io) |
| GitHub API | PyGithub |
| LinkedIn | REST API v202503 |
| Twitter/X | Tweepy v4 |
| Database | SQLite (via built-in `sqlite3`) |
| Scheduler | macOS launchd |
| Retry logic | tenacity |
