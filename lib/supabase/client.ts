import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { getSupabaseConfig } from './config';

let client: SupabaseClient | undefined;

export function createClient(): SupabaseClient {
  if (!client) {
    const { url, publishableKey } = getSupabaseConfig();
    client = createBrowserClient(url, publishableKey);
  }
  return client;
}
