import type { Metadata } from 'next';
import { Heebo } from 'next/font/google';
import { AppShell } from '@/components/AppShell';
import './globals.css';

const heebo = Heebo({
  subsets: ['hebrew', 'latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-heebo',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Stock Analyst — סורק וניתוח מניות',
  description: 'ניתוח טכני, פונדמנטלי וסנטימנט עם ציון כניסה 1-10',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="he" dir="rtl" className={heebo.variable}>
      <body className="min-h-screen bg-bg text-text font-sans antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
