import os
import re
from github import Github, Auth, GithubException
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


_BLOCK_START = "<!-- AGENT_PROJECTS_START -->"
_BLOCK_END   = "<!-- AGENT_PROJECTS_END -->"
_PROJ_START  = "<!-- PROJECT_START:{name} -->"
_PROJ_END    = "<!-- PROJECT_END:{name} -->"
_MAX_PROJECTS = 5


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30))
def update_profile_readme(readme_section: str, repo_data: dict, token: str):
    """Add or update one project inside the agent-managed block of the profile README."""
    g = Github(auth=Auth.Token(token))
    username = os.getenv("GITHUB_USERNAME", "apoorav21")

    try:
        profile_repo = g.get_repo(f"{username}/{username}")
    except GithubException:
        logger.info("Profile README repo not found — creating it")
        user = g.get_user()
        profile_repo = user.create_repo(username, description="GitHub Profile README", auto_init=True)

    repo_name = repo_data["repo_name"]

    # Fetch existing README
    try:
        readme_file = profile_repo.get_contents("README.md")
        current_content = readme_file.decoded_content.decode("utf-8")
        file_sha = readme_file.sha
    except GithubException:
        current_content = _default_readme(username)
        file_sha = None

    # Ensure the agent-managed block exists
    if _BLOCK_START not in current_content:
        current_content = current_content.rstrip() + f"\n\n{_BLOCK_START}\n{_BLOCK_END}\n"

    # Extract the block content
    block_re = re.compile(
        re.escape(_BLOCK_START) + r"(.*?)" + re.escape(_BLOCK_END),
        re.DOTALL,
    )
    match = block_re.search(current_content)
    block_body = match.group(1) if match else ""

    # Update or prepend this project's entry inside the block
    proj_start = _PROJ_START.format(name=repo_name)
    proj_end   = _PROJ_END.format(name=repo_name)
    new_entry  = f"{proj_start}\n{readme_section.strip()}\n{proj_end}"

    if proj_start in block_body:
        # Replace the existing entry
        entry_re = re.compile(
            re.escape(proj_start) + r".*?" + re.escape(proj_end),
            re.DOTALL,
        )
        block_body = entry_re.sub(new_entry, block_body)
    else:
        # Prepend so newest project appears first
        block_body = "\n" + new_entry + "\n" + block_body

    # Trim to max projects
    entries = re.findall(
        r"<!-- PROJECT_START:.*?-->.*?<!-- PROJECT_END:.*?-->",
        block_body, re.DOTALL,
    )
    if len(entries) > _MAX_PROJECTS:
        block_body = "\n" + "\n".join(entries[:_MAX_PROJECTS]) + "\n"

    new_content = block_re.sub(f"{_BLOCK_START}{block_body}{_BLOCK_END}", current_content)

    if file_sha:
        profile_repo.update_file("README.md", f"chore: update {repo_name} in profile README", new_content, file_sha)
    else:
        profile_repo.create_file("README.md", f"chore: add {repo_name} to profile README", new_content)

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

{_BLOCK_START}
{_BLOCK_END}
"""
