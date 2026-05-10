import os
import base64
from github import Github, Auth, GithubException
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


_SECTION_START = "<!-- PROJECT_START:{name} -->"
_SECTION_END = "<!-- PROJECT_END:{name} -->"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30))
def update_profile_readme(readme_section: str, repo_data: dict, token: str):
    """Add or update the repo's section in the apoorav21/apoorav21 profile README."""
    g = Github(auth=Auth.Token(token))
    username = os.getenv("GITHUB_USERNAME", "apoorav21")

    try:
        profile_repo = g.get_repo(f"{username}/{username}")
    except GithubException:
        logger.info("Profile README repo not found — creating it")
        user = g.get_user()
        profile_repo = user.create_repo(
            username,
            description="GitHub Profile README",
            auto_init=True,
        )

    repo_name = repo_data["repo_name"]
    start_marker = _SECTION_START.format(name=repo_name)
    end_marker = _SECTION_END.format(name=repo_name)

    # Fetch existing README
    try:
        readme_file = profile_repo.get_contents("README.md")
        current_content = readme_file.decoded_content.decode("utf-8")
        file_sha = readme_file.sha
    except GithubException:
        current_content = _default_readme(username)
        file_sha = None

    # Replace existing section or append
    if start_marker in current_content:
        start_idx = current_content.index(start_marker)
        end_idx = current_content.index(end_marker) + len(end_marker)
        new_section = f"{start_marker}\n{readme_section}\n{end_marker}"
        new_content = current_content[:start_idx] + new_section + current_content[end_idx:]
    else:
        new_section = f"\n{start_marker}\n{readme_section}\n{end_marker}\n"
        new_content = current_content + new_section

    commit_msg = f"chore: add {repo_name} to profile README"
    encoded = base64.b64encode(new_content.encode()).decode()

    if file_sha:
        profile_repo.update_file("README.md", commit_msg, new_content, file_sha)
    else:
        profile_repo.create_file("README.md", commit_msg, new_content)

    logger.info(f"GitHub profile README updated for {repo_name}")


def _default_readme(username: str) -> str:
    return f"""# Hi, I'm Apoorav 👋

Data Engineer | CS Student | Building in Public

- 🎓 CS @ BRCM College of Engineering (June 2026)
- 💼 Data Engineering Intern @ Caterpillar Signs (Group Bayport)
- 🛠️ Python · SQL · AWS · Airflow · DBT · LangChain
- 📫 github.com/{username}

---

## 🚀 Projects

"""
