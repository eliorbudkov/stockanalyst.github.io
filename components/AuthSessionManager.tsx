'use client';

import { useEffect } from 'react';
import { clearStoredPassword } from '@/lib/auth';

const DEFAULT_IDLE_MINUTES = 30;

// Auto-logout after inactivity: drop the stored password and return to /login.
export function AuthSessionManager() {
  useEffect(() => {
    if (
      process.env.NODE_ENV === 'development' &&
      process.env.NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL === '1'
    ) {
      return;
    }

    const configuredMinutes = Number(process.env.NEXT_PUBLIC_AUTH_IDLE_MINUTES);
    const idleMinutes =
      Number.isFinite(configuredMinutes) && configuredMinutes >= 5
        ? configuredMinutes
        : DEFAULT_IDLE_MINUTES;
    const timeoutMs = idleMinutes * 60_000;
    let timeout: ReturnType<typeof setTimeout>;
    let lastReset = 0;

    const logout = () => {
      clearStoredPassword();
      window.location.assign('/login?reason=idle');
    };

    const reset = () => {
      const now = Date.now();
      if (now - lastReset < 15_000) return;
      lastReset = now;
      clearTimeout(timeout);
      timeout = setTimeout(logout, timeoutMs);
    };

    const events: Array<keyof WindowEventMap> = ['pointerdown', 'keydown', 'scroll', 'touchstart'];
    events.forEach((event) => window.addEventListener(event, reset, { passive: true }));
    reset();

    return () => {
      clearTimeout(timeout);
      events.forEach((event) => window.removeEventListener(event, reset));
    };
  }, []);

  return null;
}
