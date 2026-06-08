'use client';

import { useState } from 'react';
import { clearStoredPassword } from '@/lib/auth';

export function SignOutButton() {
  const [loading, setLoading] = useState(false);
  const authBypassed =
    process.env.NODE_ENV === 'development' &&
    process.env.NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL === '1';

  if (authBypassed) return null;

  return (
    <button
      type="button"
      disabled={loading}
      onClick={() => {
        setLoading(true);
        clearStoredPassword();
        window.location.assign('/login');
      }}
      className="text-xs text-muted transition hover:text-text disabled:opacity-50"
    >
      {loading ? 'יוצא…' : 'יציאה'}
    </button>
  );
}
