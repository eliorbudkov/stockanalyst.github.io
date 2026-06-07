import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-heebo)', 'system-ui', 'sans-serif'],
      },
      colors: {
        bg: '#0b1020',
        panel: '#121831',
        panel2: '#1a2244',
        border: '#26305a',
        text: '#e7ecff',
        muted: '#8c97c2',
        accent: '#6ea8ff',
        good: '#3ddc97',
        warn: '#ffb454',
        bad: '#ff6b81',
      },
      boxShadow: {
        card: '0 8px 24px rgba(0, 0, 0, 0.25)',
      },
    },
  },
  plugins: [],
};

export default config;
