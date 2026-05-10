"""
Run this once to get LinkedIn OAuth tokens:
  python auth/linkedin_oauth.py

Requires LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env
"""
import os
import sys
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

CLIENT_ID = os.environ["LINKEDIN_CLIENT_ID"]
CLIENT_SECRET = os.environ["LINKEDIN_CLIENT_SECRET"]
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://127.0.0.1:8080/callback")
SCOPE = "openid profile w_member_social"
PORT = 8080

_code_received: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _code_received.append(params["code"][0])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>LinkedIn auth complete! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code")

    def log_message(self, *args):
        pass  # Suppress request logs


def run():
    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code&client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(SCOPE)}"
    )
    print(f"\nOpening LinkedIn authorization URL...\n{auth_url}\n")
    webbrowser.open(auth_url)

    print(f"Waiting for redirect on http://127.0.0.1:{PORT}/callback ...")
    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    server.handle_request()  # blocks until one request comes in

    if not _code_received:
        print("ERROR: No auth code received.")
        sys.exit(1)

    code = _code_received[0]
    print(f"Auth code received. Exchanging for tokens...")

    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    access_token = data["access_token"]
    expires_in = data.get("expires_in", 5184000)  # default 60 days
    refresh_token = data.get("refresh_token", "")
    refresh_expires_in = data.get("refresh_token_expires_in", 31536000)  # 365 days

    access_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    refresh_expiry = (datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)).isoformat()

    # Fetch person ID
    userinfo = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    ).json()
    person_id = userinfo.get("sub", "")

    print(f"\nSuccess! Person ID: {person_id}")
    print("Writing tokens to .env ...\n")

    _write_env("LINKEDIN_ACCESS_TOKEN", access_token)
    _write_env("LINKEDIN_ACCESS_TOKEN_EXPIRY", access_expiry)
    _write_env("LINKEDIN_REFRESH_TOKEN", refresh_token)
    _write_env("LINKEDIN_PERSON_ID", person_id)

    print("Done. LinkedIn OAuth setup complete.")
    print(f"Access token expires: {access_expiry}")
    print(f"Refresh token expires: {refresh_expiry}")


def _write_env(key: str, value: str):
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        env_path.write_text("")
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


if __name__ == "__main__":
    run()
