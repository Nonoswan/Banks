-- BBK Competitor Intelligence — schema
-- Run this in Supabase → SQL Editor. Safe to re-run.

-- ---------------------------------------------------------------
-- bank_posts : one row per Instagram post, per bank.
-- Already exists in your project; this is here so the schema is
-- reproducible and so the new columns get added.
-- ---------------------------------------------------------------
create table if not exists public.bank_posts (
  id             text primary key,          -- Instagram shortcode
  bank_name      text not null,
  bank_handle    text not null,
  post_url       text,
  caption        text,
  likes_count    integer not null default 0,
  comments_count integer not null default 0,
  posted_at      timestamptz,
  scraped_at     timestamptz not null default now()
);

-- Post type lets us compare reels vs static, which drives one of the
-- recommendations on the dashboard.
alter table public.bank_posts
  add column if not exists post_type text;

create index if not exists bank_posts_bank_idx   on public.bank_posts (bank_name);
create index if not exists bank_posts_posted_idx on public.bank_posts (posted_at desc);

-- ---------------------------------------------------------------
-- bank_profiles : one row per bank per scrape run.
-- Kept as an append-only snapshot rather than a single mutable row,
-- so follower growth over time is queryable later. Nothing is deleted.
-- ---------------------------------------------------------------
create table if not exists public.bank_profiles (
  id              bigint generated always as identity primary key,
  bank_name       text not null,
  bank_handle     text not null,
  followers_count integer not null default 0,
  follows_count   integer not null default 0,
  posts_count     integer not null default 0,
  full_name       text,
  biography       text,
  scraped_at      timestamptz not null default now(),
  -- Plain column, not an expression index: PostgREST's on_conflict= only
  -- accepts real column names, so the upsert target has to be storable.
  snapshot_date   date not null default ((now() at time zone 'utc')::date)
);

alter table public.bank_profiles
  add column if not exists snapshot_date date not null
  default ((now() at time zone 'utc')::date);

-- One snapshot per handle per day. Re-running the scraper the same day
-- overwrites rather than duplicating, which keeps the "latest" query honest.
create unique index if not exists bank_profiles_daily_idx
  on public.bank_profiles (bank_handle, snapshot_date);

create index if not exists bank_profiles_scraped_idx
  on public.bank_profiles (scraped_at desc);

-- ---------------------------------------------------------------
-- Row Level Security
-- The dashboard reads with the publishable (anon) key, so reads must be
-- allowed. Writes happen only via the service-role key in GitHub Actions,
-- which bypasses RLS — so no write policy is granted to anon deliberately.
-- ---------------------------------------------------------------
alter table public.bank_posts    enable row level security;
alter table public.bank_profiles enable row level security;

drop policy if exists "public read bank_posts" on public.bank_posts;
create policy "public read bank_posts"
  on public.bank_posts for select to anon, authenticated using (true);

drop policy if exists "public read bank_profiles" on public.bank_profiles;
create policy "public read bank_profiles"
  on public.bank_profiles for select to anon, authenticated using (true);

-- ---------------------------------------------------------------
-- latest_bank_profiles : most recent snapshot per bank.
-- The dashboard reads this instead of bank_profiles so it never has to
-- do "max(scraped_at)" logic in the browser.
-- ---------------------------------------------------------------
create or replace view public.latest_bank_profiles as
select distinct on (bank_handle)
  bank_name, bank_handle, followers_count, follows_count,
  posts_count, full_name, biography, scraped_at
from public.bank_profiles
order by bank_handle, scraped_at desc;
