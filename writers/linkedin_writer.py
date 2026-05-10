import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from storage import db


_POST_URL = "https://api.linkedin.com/rest/posts"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_UPLOAD_REGISTER_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"


def post(post_text: str, hashtags: list[str], image_paths: list[str] = None) -> str:
    """Post to LinkedIn. Returns the post URN."""
    token = _get_valid_token()
    person_id = db.get_context("linkedin_person_id")
    if not person_id:
        person_id = _fetch_person_id(token)
        db.set_context("linkedin_person_id", person_id)

    hashtag_str = " ".join(hashtags)
    full_text = f"{post_text}\n\n{hashtag_str}".strip()

    headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": "202503",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    # Upload images if provided
    media_assets = []
    if image_paths:
        for img_path in image_paths[:3]:
            asset_urn = _upload_image(token, person_id, img_path, headers)
            if asset_urn:
                media_assets.append(asset_urn)

    body: dict = {
        "author": f"urn:li:person:{person_id}",
        "lifecycleState": "PUBLISHED",
        "visibility": "PUBLIC",
        "commentary": full_text,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
    }

    if media_assets:
        if len(media_assets) == 1:
            body["content"] = {
                "media": {
                    "altText": "Project screenshot",
                    "id": media_assets[0],
                }
            }
        else:
            body["content"] = {
                "multiImage": {
                    "images": [
                        {"altText": f"Screenshot {i+1}", "id": urn}
                        for i, urn in enumerate(media_assets)
                    ]
                }
            }

    return _do_post(body, headers)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
def _do_post(body: dict, headers: dict) -> str:
    resp = requests.post(_POST_URL, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn post failed {resp.status_code}: {resp.text[:300]}")
    post_urn = resp.headers.get("x-restli-id") or resp.json().get("id", "")
    logger.info(f"LinkedIn post published: {post_urn}")
    return post_urn


def _upload_image(token: str, person_id: str, image_path: str, headers: dict) -> str | None:
    """Two-step LinkedIn image upload. Returns asset URN or None on failure."""
    try:
        # Step 1: Register upload
        reg_body = {
            "initializeUploadRequest": {
                "owner": f"urn:li:person:{person_id}",
            }
        }
        upload_reg_headers = {**headers, "LinkedIn-Version": "202503"}
        reg_resp = requests.post(_UPLOAD_REGISTER_URL, headers=upload_reg_headers, json=reg_body, timeout=15)
        if reg_resp.status_code not in (200, 201):
            logger.warning(f"Image registration failed: {reg_resp.status_code}")
            return None

        reg_data = reg_resp.json()["value"]
        upload_url = reg_data["uploadUrl"]
        asset_urn = reg_data["image"]

        # Step 2: Upload bytes
        with open(image_path, "rb") as f:
            img_data = f.read()

        upload_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": _mime_type(image_path),
        }
        up_resp = requests.put(upload_url, headers=upload_headers, data=img_data, timeout=30)
        if up_resp.status_code not in (200, 201):
            logger.warning(f"Image upload failed: {up_resp.status_code}")
            return None

        logger.info(f"Image uploaded: {asset_urn}")
        return asset_urn
    except Exception as e:
        logger.warning(f"Image upload error for {image_path}: {e}")
        return None


def _mime_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")


def _get_valid_token() -> str:
    """Return a valid access token, refreshing if needed."""
    token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    expiry_str = os.getenv("LINKEDIN_ACCESS_TOKEN_EXPIRY", "")

    if expiry_str:
        expiry = datetime.fromisoformat(expiry_str)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        days_left = (expiry - datetime.now(timezone.utc)).days
        if days_left <= 7:
            logger.info("LinkedIn token expiring soon — refreshing")
            token = _refresh_token()

    if not token:
        raise RuntimeError("No LinkedIn access token. Run: python auth/linkedin_oauth.py")
    return token


def _refresh_token() -> str:
    refresh = os.getenv("LINKEDIN_REFRESH_TOKEN", "")
    if not refresh:
        _notify_user("LinkedIn token expired — run: python auth/linkedin_oauth.py")
        raise RuntimeError("LinkedIn refresh token missing")

    resp = requests.post(_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": os.environ["LINKEDIN_CLIENT_ID"],
        "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
    }, timeout=15)

    if resp.status_code != 200:
        _notify_user("LinkedIn token refresh failed — run: python auth/linkedin_oauth.py")
        raise RuntimeError(f"Token refresh failed: {resp.text}")

    data = resp.json()
    new_token = data["access_token"]

    # Write back to .env file
    _update_env("LINKEDIN_ACCESS_TOKEN", new_token)
    expiry = datetime.now(timezone.utc).replace(microsecond=0)
    from datetime import timedelta
    expiry = expiry + timedelta(seconds=data.get("expires_in", 5184000))
    _update_env("LINKEDIN_ACCESS_TOKEN_EXPIRY", expiry.isoformat())

    logger.info("LinkedIn token refreshed successfully")
    return new_token


def _fetch_person_id(token: str) -> str:
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["sub"]


def _update_env(key: str, value: str):
    env_path = Path(os.getenv("BASE_DIR", Path(__file__).parent.parent)) / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text().splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n")


def _notify_user(message: str):
    import subprocess
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "Profile Agent"'],
        check=False
    )
