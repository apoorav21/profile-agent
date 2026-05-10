import os
from datetime import datetime, timezone
from github import Github, Auth
from loguru import logger

from storage.db import get_known_repo_names, get_repo_last_pushed


def check_for_new_repos(token: str, username: str, min_days_between_posts: int = 30) -> list:
    """Return list of PyGithub Repository objects that are new or significantly updated."""
    g = Github(auth=Auth.Token(token))
    user = g.get_user(username)

    known_names = get_known_repo_names()
    new_repos = []
    updated_repos = []

    # Exclude the special profile README repo (username/username)
    skip = {username.lower()}

    for repo in user.get_repos(type="owner"):
        if repo.name.lower() in skip:
            continue
        if repo.name not in known_names:
            logger.info(f"New repo detected: {repo.name}")
            new_repos.append(repo)
        else:
            # Check if repo was pushed after what we last recorded
            last_known = get_repo_last_pushed(repo.name)
            if last_known and repo.pushed_at:
                pushed_at = repo.pushed_at.replace(tzinfo=timezone.utc) if repo.pushed_at.tzinfo is None else repo.pushed_at
                last_known_dt = datetime.fromisoformat(last_known)
                if pushed_at > last_known_dt:
                    # Only re-surface if enough time has passed since last post
                    from storage.db import days_since_last_linkedin_post_for_repo
                    days = days_since_last_linkedin_post_for_repo(repo.name)
                    if days >= min_days_between_posts:
                        logger.info(f"Updated repo detected (last post {days}d ago): {repo.name}")
                        updated_repos.append(repo)

    return new_repos + updated_repos
