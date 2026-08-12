import os
import datetime
import instaloader
from supabase import create_client, Client

# Initialize Supabase Client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Target Bahrain Banks
BANKS = [
    {"name": "BBK", "handle": "bbk_online"},
    {"name": "NBB", "handle": "nbbonline"},
    {"name": "Al Salam Bank", "handle": "alsalambank"},
    {"name": "BisB", "handle": "bisbonline"},
    {"name": "NBK Bahrain", "handle": "nbkbahrain"},
]

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    save_metadata=False
)

def scrape_last_10_posts():
    for bank in BANKS:
        print(f"Scraping {bank['name']} (@{bank['handle']})...")
        try:
            profile = instaloader.Profile.from_username(L.context, bank["handle"])
            posts = profile.get_posts()
            
            count = 0
            for post in posts:
                if count >= 10:
                    break
                
                data = {
                    "id": post.shortcode,
                    "bank_name": bank["name"],
                    "bank_handle": bank["handle"],
                    "post_url": f"https://www.instagram.com/p/{post.shortcode}/",
                    "caption": (post.caption or "")[:300], # First 300 chars
                    "likes_count": post.likes,
                    "comments_count": post.comments,
                    "posted_at": post.date_utc.isoformat(),
                    "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                
                # Upsert into Supabase (Insert or Update if ID exists)
                supabase.table("bank_posts").upsert(data).execute()
                count += 1
                
        except Exception as e:
            print(f"Error scraping {bank['handle']}: {e}")

if __name__ == "__main__":
    scrape_last_10_posts()