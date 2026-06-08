import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { getSupabaseConfig } from './config';

export async function createClient() {
  const cookieStore = await cookies();
  const { url, publishableKey } = getSupabaseConfig();

  return createServerClient(url, publishableKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // Server Components cannot always write cookies. Middleware refreshes them.
        }
      },
    },
  });
}

export async function getServerAccessToken(): Promise<string | undefined> {
  if (
    process.env.NODE_ENV === 'development' &&
    process.env.NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL === '1' &&
    (!process.env.NEXT_PUBLIC_SUPABASE_URL ||
      (!process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY &&
        !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY))
  ) {
    return undefined;
  }

  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    throw new Error('Authentication session is missing');
  }
  return session.access_token;
}
