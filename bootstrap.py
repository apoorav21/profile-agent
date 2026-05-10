#!/usr/bin/env python3
"""
One-time setup script. Run this ONCE after filling in .env:

  python bootstrap.py

It will:
  1. Initialize the SQLite database
  2. Extract Apoorav.pdf → resume/resume_current.md
  3. Seed the DB with all existing GitHub repos
  4. Print a summary of what was seeded
"""
import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

from storage import db

BASE_DIR = ROOT
SOURCE_PDF = ROOT / "Apoorav.pdf"
RESUME_DIR = ROOT / "resume"


def main():
    print("\n=== Profile Agent Bootstrap ===\n")

    # 1. Init DB
    db.init_db()
    print("✓ Database initialized")

    # 2. Extract resume PDF
    RESUME_DIR.mkdir(exist_ok=True)
    if SOURCE_PDF.exists():
        try:
            from writers.resume_writer import bootstrap_from_pdf
            bootstrap_from_pdf(str(SOURCE_PDF))
            print(f"✓ Resume extracted: resume/resume_current.md")
            print("  → Open resume/resume_current.md and clean it up before the agent runs.")
        except Exception as e:
            print(f"✗ Resume extraction failed: {e}")
            print("  Install pymupdf4llm: pip install pymupdf4llm")
    else:
        print(f"✗ Apoorav.pdf not found at {SOURCE_PDF}")
        print("  Place your resume PDF at the project root as 'Apoorav.pdf'")

    # 3. Seed existing GitHub repos
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        print("\n✗ GITHUB_TOKEN not set — skipping repo seed. Add it to .env first.")
        return

    print("\nFetching your GitHub repos...")
    try:
        from github import Github, Auth
        from analyzers.repo_analyzer import analyze
        g = Github(auth=Auth.Token(token))
        user = g.get_user(os.getenv("GITHUB_USERNAME", "apoorav21"))
        repos = list(user.get_repos(type="owner"))
        print(f"  Found {len(repos)} repos")

        for repo in repos:
            print(f"  Seeding: {repo.name} ...", end=" ", flush=True)
            try:
                data = analyze(repo, token)
                db.save_repository(data)
                print("✓")
            except Exception as e:
                print(f"✗ ({e})")

        print(f"\n✓ Seeded {len(repos)} repos into the database")
    except Exception as e:
        print(f"✗ GitHub seeding failed: {e}")

    print("\n=== Next steps ===")
    print("1. Review and clean resume/resume_current.md")
    print("2. Run: python auth/linkedin_oauth.py")
    print("3. Add Twitter keys to .env, run: python auth/twitter_setup_check.py")
    print("4. Create the apoorav21/apoorav21 GitHub repo (profile README)")
    print("5. Test dry run: ENABLE_LINKEDIN_POSTING=false ENABLE_TWITTER_POSTING=false python orchestrator/main.py")
    print("6. Install scheduler: cp launchd/com.apoorav.profileagent.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.apoorav.profileagent.plist")
    print("\nSetup complete!\n")


if __name__ == "__main__":
    main()
