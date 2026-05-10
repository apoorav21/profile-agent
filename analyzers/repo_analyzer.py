import re
import os
import json
import tempfile
import requests
from pathlib import Path
from datetime import timezone
from github import Repository
from loguru import logger
from openai import OpenAI


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_IMAGE_DIRS = {"screenshots", "images", "assets", "demo", "docs", "media", "preview"}


def analyze(repo: "Repository.Repository", github_token: str) -> dict:
    """Deep-analyze a GitHub repo and return a structured dict."""
    logger.info(f"Analyzing repo: {repo.full_name}")

    readme_md = _fetch_readme(repo)
    languages = _fetch_languages(repo)
    topics = repo.get_topics()
    images = _find_images(repo, readme_md, github_token)

    pushed_at = repo.pushed_at
    if pushed_at and pushed_at.tzinfo is None:
        pushed_at = pushed_at.replace(tzinfo=timezone.utc)

    key_features = _extract_key_features(repo.name, repo.description or "", readme_md)

    return {
        "repo_name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description or "",
        "language": repo.language or "",
        "languages": languages,
        "topics": topics,
        "readme_md": readme_md,
        "key_features": key_features,
        "stars": repo.stargazers_count,
        "created_at": repo.created_at.isoformat() if repo.created_at else None,
        "last_pushed": pushed_at.isoformat() if pushed_at else None,
        "images": images,  # list of local tmp file paths
        "url": repo.html_url,
    }


def _fetch_readme(repo) -> str:
    try:
        content = repo.get_readme()
        return content.decoded_content.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _fetch_languages(repo) -> dict:
    try:
        return dict(repo.get_languages())
    except Exception:
        return {}


def _find_images(repo, readme_md: str, token: str) -> list[str]:
    """Download up to 3 images from the repo. Returns list of tmp file paths."""
    candidates: list[str] = []

    # 1. Look for images in known image directories
    try:
        contents = repo.get_contents("")
        for item in contents:
            if item.type == "dir" and item.name.lower() in _IMAGE_DIRS:
                sub = repo.get_contents(item.path)
                for f in sub:
                    if Path(f.name).suffix.lower() in _IMAGE_EXTS:
                        candidates.append(f.download_url)
    except Exception:
        pass

    # 2. Extract images from README markdown
    readme_images = re.findall(r"!\[.*?\]\((https?://[^\s)]+)\)", readme_md)
    for url in readme_images:
        if any(url.lower().endswith(ext) for ext in _IMAGE_EXTS):
            candidates.append(url)

    # No real images found — return empty so LinkedIn posts text-only
    if not candidates:
        return []

    # Download up to 3 unique candidates
    downloaded = []
    seen_urls: set[str] = set()
    headers = {"Authorization": f"token {token}"}

    for url in candidates:
        if len(downloaded) >= 3:
            break
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 1024:
                suffix = Path(url.split("?")[0]).suffix or ".png"
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix, prefix=f"profile_agent_{repo.name}_"
                )
                tmp.write(resp.content)
                tmp.close()
                downloaded.append(tmp.name)
                logger.info(f"Downloaded image: {url} → {tmp.name}")
        except Exception as e:
            logger.warning(f"Failed to download image {url}: {e}")

    return downloaded


def _extract_key_features(repo_name: str, description: str, readme_md: str) -> list[str]:
    """Use GPT-4o-mini to extract 3-5 key features from the repo."""
    if not readme_md and not description:
        return []

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    content = f"Repository: {repo_name}\nDescription: {description}\n\nREADME:\n{readme_md[:3000]}"

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract 3-5 key technical features or achievements from this GitHub repo. "
                        "Return a JSON array of short strings (max 15 words each). "
                        "Focus on: what it does, key technologies, notable techniques, scale/impact. "
                        "Return ONLY the JSON array, no other text."
                    )
                },
                {"role": "user", "content": content}
            ],
            max_completion_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fence if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Key feature extraction failed for {repo_name}: {e}")
        return [description] if description else []
