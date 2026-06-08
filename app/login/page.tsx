'use client';

import { useState } from 'react';
import { authCheck } from '@/lib/api';
import { setStoredPassword } from '@/lib/auth';

function safeNext(): string {
  if (typeof window === 'undefined') return '/';
  const next = new URLSearchParams(window.location.search).get('next');
  // Only allow same-site relative paths (block //evil.com open redirects).
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const ok = await authCheck(password);
      if (!ok) {
        setError('סיסמה שגויה.');
        return;
      }
      setStoredPassword(password);
      window.location.assign(safeNext());
    } catch {
      setError('לא ניתן להתחבר לשרת כרגע (ייתכן שהשרת מתעורר) — נסה שוב בעוד רגע.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-bg px-4 py-10" dir="rtl">
      <section className="w-full max-w-sm rounded-lg border border-border bg-panel p-6 shadow-card">
        <div className="mb-6">
          <div className="mb-3 grid h-10 w-10 place-items-center rounded-lg bg-accent/20 text-xl font-bold text-accent">
            S
          </div>
          <h1 className="text-xl font-bold">כניסה ל־Stock Analyst</h1>
          <p className="mt-1 text-sm text-muted">הזן את סיסמת הגישה לאתר.</p>
        </div>

        <form className="space-y-4" onSubmit={signIn}>
          <label className="block">
            <span className="mb-1.5 block text-xs text-muted">סיסמה</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              autoFocus
              required
              dir="ltr"
              className="h-11 w-full rounded-md border border-border bg-bg px-3 text-left outline-none focus:border-accent"
            />
          </label>

          {error && (
            <div className="rounded-md border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="h-11 w-full rounded-md bg-accent font-semibold text-bg transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60"
          >
            {loading ? 'מתחבר…' : 'כניסה'}
          </button>
        </form>
      </section>
    </main>
  );
}
