'use client';

import { usePathname } from 'next/navigation';
import { AuthSessionManager } from './AuthSessionManager';
import { SignOutButton } from './SignOutButton';

const AUTH_PATHS = ['/login', '/auth/mfa'];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthPage = AUTH_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));

  if (isAuthPage) return children;

  return (
    <>
      <AuthSessionManager />
      <div className="mx-auto max-w-7xl px-3 py-4 sm:px-4 sm:py-6">
        <header className="mb-6 flex items-center justify-between sm:mb-8">
          <a href="/" className="flex items-center gap-2 sm:gap-3">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent/20 text-accent text-lg font-bold sm:h-10 sm:w-10 sm:rounded-xl sm:text-xl">
              S
            </div>
            <div>
              <div className="text-base font-semibold sm:text-lg">Stock Analyst</div>
              <div className="text-[10px] text-muted sm:text-xs">סורק וניתוח מניות</div>
            </div>
          </a>
          <nav className="flex items-center gap-3 text-sm text-muted sm:gap-4">
            <a href="/" className="hover:text-text">דשבורד</a>
            <SignOutButton />
          </nav>
        </header>
        <main>{children}</main>
        <footer className="mt-12 border-t border-border pt-4 text-center text-[11px] text-muted sm:mt-16 sm:pt-6 sm:text-xs">
          הכלי נועד לחקר ולמידה בלבד. אינו מהווה ייעוץ השקעות.
        </footer>
      </div>
    </>
  );
}
