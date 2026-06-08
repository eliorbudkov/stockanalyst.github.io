'use client';

import { useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';

type Mode = 'loading' | 'enroll' | 'challenge';

export default function MfaPage() {
  const [mode, setMode] = useState<Mode>('loading');
  const [factorId, setFactorId] = useState('');
  const [qrCode, setQrCode] = useState('');
  const [secret, setSecret] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;

    async function prepareMfa() {
      try {
        const supabase = createClient();
        const { data, error: listError } = await supabase.auth.mfa.listFactors();
        if (listError) throw listError;

        const verified = data.totp.find((factor) => factor.status === 'verified');
        if (verified) {
          if (!active) return;
          setFactorId(verified.id);
          setMode('challenge');
          return;
        }

        const { data: enrollment, error: enrollError } = await supabase.auth.mfa.enroll({
          factorType: 'totp',
          friendlyName: 'Stock Analyst',
        });
        if (enrollError) throw enrollError;
        if (!active) return;

        setFactorId(enrollment.id);
        setQrCode(enrollment.totp.qr_code);
        setSecret(enrollment.totp.secret);
        setMode('enroll');
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'הכנת MFA נכשלה');
      }
    }

    void prepareMfa();
    return () => {
      active = false;
    };
  }, []);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    if (!factorId || code.length !== 6) return;
    setError(null);
    setLoading(true);

    try {
      const supabase = createClient();
      const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({
        factorId,
      });
      if (challengeError) throw challengeError;

      const { error: verifyError } = await supabase.auth.mfa.verify({
        factorId,
        challengeId: challenge.id,
        code,
      });
      if (verifyError) throw verifyError;

      const destination = sessionStorage.getItem('stock-analyst:post-auth-path') || '/';
      sessionStorage.removeItem('stock-analyst:post-auth-path');
      window.location.assign(destination);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'הקוד אינו תקין');
      setCode('');
    } finally {
      setLoading(false);
    }
  }

  async function signOut() {
    await createClient().auth.signOut();
    window.location.assign('/login');
  }

  return (
    <main className="grid min-h-screen place-items-center bg-bg px-4 py-10" dir="rtl">
      <section className="w-full max-w-md rounded-lg border border-border bg-panel p-6 shadow-card">
        <h1 className="text-xl font-bold">
          {mode === 'enroll' ? 'הגדרת אימות דו־שלבי' : 'אימות דו־שלבי'}
        </h1>

        {mode === 'loading' && !error && (
          <p className="mt-4 text-sm text-muted">בודק את אמצעי האימות…</p>
        )}

        {mode === 'enroll' && (
          <div className="mt-5 space-y-4">
            <p className="text-sm text-muted">
              סרוק את הקוד באמצעות Google Authenticator, Microsoft Authenticator או 1Password.
            </p>
            {qrCode && (
              <div className="mx-auto w-fit rounded-md bg-white p-3">
                <img src={qrCode} alt="QR להגדרת Authenticator" className="h-48 w-48" />
              </div>
            )}
            <div className="rounded-md border border-border bg-bg p-3 text-xs text-muted">
              קוד ידני:
              <code className="ltr mt-1 block break-all text-text">{secret}</code>
            </div>
          </div>
        )}

        {mode === 'challenge' && (
          <p className="mt-2 text-sm text-muted">הזן את הקוד בן 6 הספרות מאפליקציית האימות.</p>
        )}

        {mode !== 'loading' && (
          <form className="mt-5 space-y-4" onSubmit={verify}>
            <input
              type="text"
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              required
              minLength={6}
              maxLength={6}
              dir="ltr"
              className="h-12 w-full rounded-md border border-border bg-bg text-center text-2xl font-bold tracking-[0.35em] outline-none focus:border-accent"
            />
            <button
              type="submit"
              disabled={loading || code.length !== 6}
              className="h-11 w-full rounded-md bg-accent font-semibold text-bg transition hover:brightness-110 disabled:cursor-wait disabled:opacity-50"
            >
              {loading ? 'מאמת…' : mode === 'enroll' ? 'הפעל MFA' : 'כניסה'}
            </button>
          </form>
        )}

        {error && (
          <div className="mt-4 rounded-md border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
            {error}
          </div>
        )}

        <button type="button" onClick={signOut} className="mt-5 text-xs text-muted hover:text-text">
          יציאה מהחשבון
        </button>
      </section>
    </main>
  );
}
