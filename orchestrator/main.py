#!/usr/bin/env python3
"""
Profile Agent — main entry point.
Run manually: python orchestrator/main.py
Or installed as a launchd agent (runs daily at 10am).
"""
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# Make project root importable regardless of cwd
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from loguru import logger
from storage import db
from monitors.github_monitor import check_for_new_repos
from analyzers.repo_analyzer import analyze
from brain.openai_brain import generate
from writers import github_writer, resume_writer, linkedin_writer, twitter_writer


# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_FILE = ROOT / "logs" / "agent.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
logger.add(str(LOG_FILE), rotation="10 MB", retention="30 days", level="DEBUG")


# ── Config ─────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "apoorav21")
ENABLE_LINKEDIN = os.getenv("ENABLE_LINKEDIN_POSTING", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER_POSTING", "true").lower() == "true"
ENABLE_RESUME = os.getenv("ENABLE_RESUME_UPDATE", "true").lower() == "true"
ENABLE_GITHUB_README = os.getenv("ENABLE_GITHUB_README_UPDATE", "true").lower() == "true"
MIN_DAYS_BETWEEN_POSTS = int(os.getenv("MIN_DAYS_BETWEEN_REPO_POSTS", "30"))


def run_pipeline():
    start_time = time.time()
    run_record: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "trigger": "scheduled",
        "new_repos": [],
        "actions_taken": [],
        "errors": [],
    }

    logger.info("=" * 60)
    logger.info("Profile Agent starting")

    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN not set in .env — aborting")
        return

    # 1. Init DB
    db.init_db()

    # 2. Check GitHub for new/updated repos
    try:
        new_repos = check_for_new_repos(GITHUB_TOKEN, GITHUB_USERNAME, MIN_DAYS_BETWEEN_POSTS)
    except Exception as e:
        logger.error(f"GitHub monitor failed: {e}")
        _notify(f"Profile Agent error: GitHub monitor failed — {e}")
        run_record["errors"].append(f"github_monitor: {e}")
        db.log_run({**run_record, "duration_s": time.time() - start_time})
        return

    if not new_repos:
        logger.info("No new repositories detected. Done.")
        db.log_run({**run_record, "duration_s": time.time() - start_time})
        return

    run_record["new_repos"] = [r.name for r in new_repos]
    logger.info(f"Detected {len(new_repos)} repo(s): {run_record['new_repos']}")

    # 3. Process each repo
    for repo in new_repos:
        _process_repo(repo, run_record)
        if len(new_repos) > 1:
            time.sleep(30)  # be polite between repos

    duration = time.time() - start_time
    run_record["duration_s"] = duration

    success = len(run_record["actions_taken"])
    errors = len(run_record["errors"])
    _notify(f"Done in {duration:.0f}s. {success} actions, {errors} errors.")
    logger.info(f"Pipeline complete in {duration:.1f}s")

    db.log_run(run_record)


def _process_repo(repo, run_record: dict):
    repo_name = repo.name
    logger.info(f"Processing: {repo_name}")

    # Analyze
    try:
        repo_data = analyze(repo, GITHUB_TOKEN)
        db.save_repository(repo_data)
    except Exception as e:
        logger.error(f"Analysis failed for {repo_name}: {e}")
        run_record["errors"].append(f"analyze:{repo_name}: {e}")
        return

    # Generate content
    try:
        context = db.get_full_context()
        brain_out = generate(repo_data, context)
    except Exception as e:
        logger.error(f"Brain call failed for {repo_name}: {e}")
        run_record["errors"].append(f"brain:{repo_name}: {e}")
        return

    images = repo_data.get("images", [])

    # GitHub README
    if ENABLE_GITHUB_README:
        try:
            github_writer.update_profile_readme(brain_out.github_readme_section, repo_data, GITHUB_TOKEN)
            run_record["actions_taken"].append(f"github_readme:{repo_name}")
        except Exception as e:
            logger.error(f"GitHub README update failed: {e}")
            run_record["errors"].append(f"github_readme:{repo_name}: {e}")

    # Resume
    if ENABLE_RESUME:
        try:
            pdf_path = resume_writer.update_resume(brain_out, repo_data)
            run_record["actions_taken"].append(f"resume:{repo_name}")
            _notify(f"Resume updated: {repo_name} added")
        except Exception as e:
            logger.error(f"Resume update failed: {e}")
            run_record["errors"].append(f"resume:{repo_name}: {e}")

    # LinkedIn
    if ENABLE_LINKEDIN:
        try:
            post_urn = linkedin_writer.post(
                brain_out.linkedin_post,
                brain_out.linkedin_hashtags,
                image_paths=images,
            )
            db.save_linkedin_post({
                "repo_name": repo_name,
                "post_text": brain_out.linkedin_post,
                "post_urn": post_urn,
                "tone": brain_out.linkedin_tone,
                "themes": brain_out.linkedin_themes,
                "hashtags": brain_out.linkedin_hashtags,
                "has_image": bool(images),
            })
            run_record["actions_taken"].append(f"linkedin:{repo_name}")
        except Exception as e:
            logger.error(f"LinkedIn post failed: {e}")
            run_record["errors"].append(f"linkedin:{repo_name}: {e}")

    # Twitter
    if ENABLE_TWITTER:
        try:
            tweet_id = twitter_writer.post(
                brain_out.tweet,
                brain_out.tweet_hashtags,
                repo_data.get("url", f"https://github.com/{GITHUB_USERNAME}/{repo_name}"),
                image_paths=images,
            )
            db.save_tweet({
                "repo_name": repo_name,
                "tweet_text": brain_out.tweet,
                "tweet_id": tweet_id,
                "hook_type": brain_out.tweet_hook,
                "hashtags": brain_out.tweet_hashtags,
                "has_image": bool(images),
            })
            run_record["actions_taken"].append(f"twitter:{repo_name}")
        except Exception as e:
            logger.error(f"Twitter post failed: {e}")
            run_record["errors"].append(f"twitter:{repo_name}: {e}")

    # Update narrative arc
    try:
        db.set_context("narrative_arc", brain_out.narrative_arc_update)
    except Exception:
        pass

    # Clean up temp images
    import os as _os
    for img in images:
        try:
            _os.unlink(img)
        except Exception:
            pass


def _notify(message: str):
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "Profile Agent"'],
        check=False, capture_output=True,
    )


def run_single_repo(repo_name: str):
    """Force-process a specific repo by name, regardless of whether it's new."""
    from github import Github, Auth

    start_time = time.time()
    run_record: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "trigger": f"manual:{repo_name}",
        "new_repos": [repo_name],
        "actions_taken": [],
        "errors": [],
    }

    logger.info("=" * 60)
    logger.info(f"Profile Agent — manual run for repo: {repo_name}")

    db.init_db()

    g = Github(auth=Auth.Token(GITHUB_TOKEN))
    try:
        repo = g.get_repo(f"{GITHUB_USERNAME}/{repo_name}")
    except Exception as e:
        logger.error(f"Could not fetch repo {repo_name}: {e}")
        return

    _process_repo(repo, run_record)

    duration = time.time() - start_time
    run_record["duration_s"] = duration
    db.log_run(run_record)
    logger.info(f"Manual run complete in {duration:.1f}s")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Profile Agent")
    parser.add_argument("--repo", metavar="REPO_NAME",
                        help="Force-process a specific repo by name (skips new-repo detection)")
    args = parser.parse_args()

    if args.repo:
        run_single_repo(args.repo)
    else:
        run_pipeline()
