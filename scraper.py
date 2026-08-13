"""
BBK Competitor Intelligence — Instagram collector.

Replaces the previous instaloader implementation, which could not work from a
GitHub Actions runner: Instagram rate-limits and blocks datacenter IPs, and the
old code swallowed those failures so the job still exited 0 and showed green.

This version fetches through Apify (residential proxies, handled for us) and
fails loudly — a run that collects nothing exits non-zero.
"""

import os
import sys
import datetime
from typing import Any

import requests
from supabase import create_client, Client

# --- Configuration -----------------------------------------------------------

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Instagram handles, each verified against the live account's og:title on
# 13 Aug 2026. Re-verify if you add one: a wrong handle silently produces a
# bank with zero engagement, which is worse than an error because it reads
# as a finding rather than a bug.
BANKS = [
    {"name": "BBK", "handle": "bbk_online"},
    {"name": "NBB", "handle": "nbbonline"},
    {"name": "Al Salam Bank", "handle": "alsalambank"},
    {"name": "BisB", "handle": "bisbonline"},
    {"name": "NBK Bahrain", "handle": "nbkbahrain"},
    {"name": "ila Bank", "handle": "ilabank"},
]

POSTS_PER_BANK = 10
APIFY_ACTOR = "apify~instagram-scraper"
APIFY_ENDPOINT = (
    f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
)


def require_env() -> None:
    """Fail before doing any work if the run cannot possibly succeed."""
    missing = [
        name
        for name, value in (
            ("APIFY_TOKEN", APIFY_TOKEN),
            ("SUPABASE_URL", SUPABASE_URL),
            ("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_KEY),
        )
        if not value
    ]
    if missing:
        sys.exit(f"FATAL: missing required environment variables: {', '.join(missing)}")


def fetch_from_apify() -> list[dict[str, Any]]:
    """One Apify run for all handles. Returns raw profile records."""
    payload = {
        "directUrls": [
            f"https://www.instagram.com/{bank['handle']}/" for bank in BANKS
        ],
        "resultsType": "details",
        "resultsLimit": POSTS_PER_BANK,
        "addParentData": False,
    }

    print(f"Requesting {len(BANKS)} profiles from Apify...")
    response = requests.post(
        APIFY_ENDPOINT,
        json=payload,
        # Token goes in the header, never the query string — query strings end
        # up in proxy logs and CI output.
        headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
        timeout=300,
    )

    if response.status_code >= 400:
        sys.exit(
            f"FATAL: Apify returned {response.status_code}: {response.text[:500]}"
        )

    items = response.json()
    if not isinstance(items, list):
        sys.exit(f"FATAL: unexpected Apify response shape: {type(items).__name__}")

    print(f"Apify returned {len(items)} profile record(s).")
    return items


def main() -> None:
    require_env()
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    handle_to_name = {bank["handle"].lower(): bank["name"] for bank in BANKS}
    items = fetch_from_apify()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    profile_rows: list[dict[str, Any]] = []
    post_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for item in items:
        handle = (item.get("username") or "").lower()
        bank_name = handle_to_name.get(handle)
        if not bank_name:
            print(f"  ! skipping unrecognised handle in response: {handle!r}")
            continue

        if item.get("error"):
            failures.append(f"{handle}: {item['error']}")
            continue

        profile_rows.append(
            {
                "bank_name": bank_name,
                "bank_handle": handle,
                "followers_count": item.get("followersCount") or 0,
                "follows_count": item.get("followsCount") or 0,
                "posts_count": item.get("postsCount") or 0,
                "full_name": item.get("fullName"),
                "biography": item.get("biography"),
                "scraped_at": now,
            }
        )

        latest_posts = item.get("latestPosts") or []
        if not latest_posts:
            failures.append(f"{handle}: profile returned but no posts")

        for post in latest_posts[:POSTS_PER_BANK]:
            shortcode = post.get("shortCode")
            if not shortcode:
                continue
            post_rows.append(
                {
                    "id": shortcode,
                    "bank_name": bank_name,
                    "bank_handle": handle,
                    "post_url": post.get("url")
                    or f"https://www.instagram.com/p/{shortcode}/",
                    "caption": (post.get("caption") or "")[:300],
                    "likes_count": post.get("likesCount") or 0,
                    "comments_count": post.get("commentsCount") or 0,
                    "post_type": post.get("type"),
                    "posted_at": post.get("timestamp"),
                    "scraped_at": now,
                }
            )

        print(f"  {bank_name:<15} {len(latest_posts):>2} posts")

    # Write. Upserts so re-runs update rather than duplicate.
    if profile_rows:
        supabase.table("bank_profiles").upsert(
            profile_rows, on_conflict="bank_handle,snapshot_date"
        ).execute()
    if post_rows:
        supabase.table("bank_posts").upsert(post_rows, on_conflict="id").execute()

    print(f"\nWrote {len(profile_rows)} profile(s), {len(post_rows)} post(s).")

    for failure in failures:
        print(f"  ! {failure}", file=sys.stderr)

    # Fail loudly. The old scraper's defining bug was exiting 0 on total failure,
    # so a green tick meant nothing. These are the two states worth alerting on.
    if not post_rows:
        sys.exit("FATAL: no posts collected — nothing was written.")
    if len(profile_rows) < len(BANKS):
        sys.exit(
            f"FATAL: expected {len(BANKS)} profiles, got {len(profile_rows)}. "
            "Check the handles in BANKS."
        )


if __name__ == "__main__":
    main()
