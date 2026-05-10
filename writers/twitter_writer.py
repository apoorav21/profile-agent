import os
from pathlib import Path
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
import tweepy


def post(tweet_text: str, hashtags: list[str], repo_url: str, image_paths: list[str] = None) -> str:
    """Post to Twitter/X. Returns tweet ID."""
    client = _get_client()
    api_v1 = _get_api_v1()  # needed for media upload

    hashtag_str = " ".join(hashtags)
    full_text = f"{tweet_text}\n\n{repo_url} {hashtag_str}".strip()

    # Truncate if over 280 chars
    if len(full_text) > 280:
        overflow = len(full_text) - 280
        tweet_text = tweet_text[:len(tweet_text) - overflow - 3] + "..."
        full_text = f"{tweet_text}\n\n{repo_url} {hashtag_str}".strip()

    media_ids = []
    if image_paths and api_v1:
        for img_path in image_paths[:4]:
            media_id = _upload_media(api_v1, img_path)
            if media_id:
                media_ids.append(media_id)

    return _create_tweet(client, full_text, media_ids or None)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
def _create_tweet(client: tweepy.Client, text: str, media_ids: list | None) -> str:
    kwargs: dict = {"text": text}
    if media_ids:
        kwargs["media_ids"] = media_ids
    resp = client.create_tweet(**kwargs)
    tweet_id = resp.data["id"]
    logger.info(f"Tweet posted: {tweet_id}")
    return tweet_id


def _upload_media(api: tweepy.API, image_path: str) -> str | None:
    try:
        suffix = Path(image_path).suffix.lower()
        is_gif = suffix == ".gif"
        media = api.media_upload(
            filename=image_path,
            media_category="tweet_gif" if is_gif else "tweet_image",
        )
        return str(media.media_id)
    except Exception as e:
        logger.warning(f"Media upload failed for {image_path}: {e}")
        return None


def _get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )


def _get_api_v1() -> tweepy.API | None:
    """v1.1 API needed only for media uploads."""
    try:
        auth = tweepy.OAuth1UserHandler(
            os.environ["TWITTER_API_KEY"],
            os.environ["TWITTER_API_SECRET"],
            os.environ["TWITTER_ACCESS_TOKEN"],
            os.environ["TWITTER_ACCESS_SECRET"],
        )
        return tweepy.API(auth)
    except Exception as e:
        logger.warning(f"Twitter v1 API init failed (image upload disabled): {e}")
        return None
