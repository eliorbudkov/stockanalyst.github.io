import { NextResponse, type NextRequest } from 'next/server';
import { AUTH_MARKER_COOKIE } from '@/lib/auth';

const PUBLIC_PATHS = ['/login'];

function isPublicPath(pathname: string) {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

// UX-only gate. The real security boundary is the backend, which rejects any
// request whose Bearer token doesn't match APP_PASSWORD. This middleware just
// keeps logged-out visitors on /login; the marker cookie holds no secret.
export function middleware(request: NextRequest) {
  // Unconfigured local dev: no auth at all, so don't gate anything.
  if (
    process.env.NODE_ENV === 'development' &&
    process.env.NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL === '1'
  ) {
    return NextResponse.next();
  }

  const pathname = request.nextUrl.pathname;
  const hasMarker = request.cookies.get(AUTH_MARKER_COOKIE)?.value === '1';

  if (!hasMarker) {
    if (isPublicPath(pathname)) return NextResponse.next();
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = '/login';
    loginUrl.search = '';
    loginUrl.searchParams.set('next', `${pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(loginUrl);
  }

  if (isPublicPath(pathname)) {
    const homeUrl = request.nextUrl.clone();
    homeUrl.pathname = '/';
    homeUrl.search = '';
    return NextResponse.redirect(homeUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
