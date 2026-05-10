"""
Run this to verify your Twitter/X credentials work:
  python auth/twitter_setup_check.py

Requires all 4 TWITTER_* vars in .env
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import tweepy

load_dotenv(Path(__file__).parent.parent / ".env")

def run():
    required = ["TWITTER_API_KEY", "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"ERROR: Missing .env keys: {missing}")
        sys.exit(1)

    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )

    me = client.get_me()
    print(f"\nTwitter credentials valid!")
    print(f"Authenticated as: @{me.data.username} (ID: {me.data.id})")
    print("\nSetup complete. Your agent can now post tweets.")


if __name__ == "__main__":
    run()
