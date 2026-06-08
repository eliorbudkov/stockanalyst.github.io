-- Require a verified MFA session (aal2) for all user-owned application data.

drop policy if exists "watchlist_select_own" on public.watchlist;
drop policy if exists "watchlist_insert_own" on public.watchlist;
drop policy if exists "watchlist_update_own" on public.watchlist;
drop policy if exists "watchlist_delete_own" on public.watchlist;

create policy "watchlist_select_own_aal2" on public.watchlist
    for select using (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');
create policy "watchlist_insert_own_aal2" on public.watchlist
    for insert with check (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');
create policy "watchlist_update_own_aal2" on public.watchlist
    for update
    using (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2')
    with check (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');
create policy "watchlist_delete_own_aal2" on public.watchlist
    for delete using (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');

drop policy if exists "analysis_history_select_own" on public.analysis_history;
drop policy if exists "analysis_history_insert_own" on public.analysis_history;

create policy "analysis_history_select_own_aal2" on public.analysis_history
    for select using (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');
create policy "analysis_history_insert_own_aal2" on public.analysis_history
    for insert with check (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');

drop policy if exists "alerts_all_own" on public.alerts;
create policy "alerts_all_own_aal2" on public.alerts
    for all
    using (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2')
    with check (auth.uid() = user_id and (auth.jwt() ->> 'aal') = 'aal2');

drop policy if exists "news_public_read" on public.news_items;
create policy "news_authenticated_aal2_read" on public.news_items
    for select using ((auth.jwt() ->> 'aal') = 'aal2');
