-- Stock Analyst — initial schema
-- Run with: supabase db push    (after `supabase link --project-ref <ref>`)
-- Or paste into the Supabase SQL Editor.

-- pgvector for future AI embeddings (news / report semantic search)
create extension if not exists "vector";
create extension if not exists "pgcrypto";

-- ─────────────────────────────────────────────────────────────────────────────
-- Watchlist — one row per (user, symbol)
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.watchlist (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    symbol      text not null,
    note        text,
    created_at  timestamptz not null default now(),
    unique (user_id, symbol)
);

create index if not exists watchlist_user_idx on public.watchlist(user_id);

alter table public.watchlist enable row level security;

create policy "watchlist_select_own" on public.watchlist
    for select using (auth.uid() = user_id);
create policy "watchlist_insert_own" on public.watchlist
    for insert with check (auth.uid() = user_id);
create policy "watchlist_update_own" on public.watchlist
    for update using (auth.uid() = user_id);
create policy "watchlist_delete_own" on public.watchlist
    for delete using (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Analysis history — snapshot of computed score per symbol per run
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.analysis_history (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid references auth.users(id) on delete cascade,
    symbol          text not null,
    score           numeric(4,2) not null,
    breakdown       jsonb not null,
    rationale       jsonb not null,
    price           numeric(14,4),
    rsi14           numeric(6,2),
    atr_pct         numeric(6,2),
    created_at      timestamptz not null default now()
);

create index if not exists analysis_history_symbol_idx on public.analysis_history(symbol, created_at desc);
create index if not exists analysis_history_user_idx on public.analysis_history(user_id, created_at desc);

alter table public.analysis_history enable row level security;

create policy "analysis_history_select_own" on public.analysis_history
    for select using (auth.uid() = user_id or user_id is null);
create policy "analysis_history_insert_own" on public.analysis_history
    for insert with check (auth.uid() = user_id or user_id is null);

-- ─────────────────────────────────────────────────────────────────────────────
-- Alerts — phase-2; stub now so we can build against it
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.alerts (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    symbol       text not null,
    -- 'price_above' | 'price_below' | 'rsi_above' | 'rsi_below' | 'score_above'
    kind         text not null,
    threshold    numeric(14,4) not null,
    enabled      boolean not null default true,
    triggered_at timestamptz,
    created_at   timestamptz not null default now()
);

create index if not exists alerts_user_idx on public.alerts(user_id, enabled);

alter table public.alerts enable row level security;
create policy "alerts_all_own" on public.alerts
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- News / sentiment cache — phase-2; pgvector for semantic search
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.news_items (
    id            uuid primary key default gen_random_uuid(),
    symbol        text not null,
    source        text,
    headline      text not null,
    url           text,
    published_at  timestamptz,
    sentiment     numeric(4,3),     -- -1..+1 from Claude Haiku
    summary       text,
    embedding     vector(1536),     -- for semantic dedup / "similar story" search
    created_at    timestamptz not null default now()
);

create index if not exists news_symbol_idx on public.news_items(symbol, published_at desc);
-- IVFFlat index for vector similarity (build after >1k rows)
-- create index news_embedding_idx on public.news_items using ivfflat (embedding vector_cosine_ops);

-- News is public-read (so all users see the same sentiment cache)
alter table public.news_items enable row level security;
create policy "news_public_read" on public.news_items for select using (true);
