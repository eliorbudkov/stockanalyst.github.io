# Stock Analyst

הוראות הפריסה המעודכנות ל־Vercel, Render ו־GitHub Actions נמצאות ב־
[DEPLOYMENT.md](DEPLOYMENT.md).

אפליקציית ווב לסריקה וניתוח מניות עם **ציון כניסה סופי 1-10** המבוסס על שקלול
מגמה, מומנטום, תנודתיות, נפח ופונדמנטלס.

> ⚠️ הכלי נועד למחקר ולמידה בלבד. אינו מהווה ייעוץ השקעות.

## ארכיטקטורה (MVP)

```
┌─────────────────────────┐      HTTPS        ┌─────────────────────────┐
│  Next.js 15 (App Router)│  ───────────────▶ │  FastAPI (Python)       │
│  TypeScript + Tailwind  │                   │  yfinance + pandas      │
│  Lightweight Charts     │                   │  indicators + scoring   │
│  Vercel                 │                   │  Railway / Render       │
└──────────┬──────────────┘                   └─────────────────────────┘
           │
           │  (phase 2)
           ▼
┌─────────────────────────┐
│  Supabase (Postgres)    │
│  + pgvector             │
│  Auth · DB · Storage    │
└─────────────────────────┘
```

## מה ה-MVP כולל
- ✅ חיפוש סימול → גרף נרות אינטראקטיבי (lightweight-charts)
- ✅ ממוצעים נעים: MA(20, 50, 150, 200) על הגרף
- ✅ אינדיקטורים: RSI(14), ATR(14), ניתוח נפח
- ✅ פונדמנטלס: שווי שוק, P/E, P/B, דיבידנד, ביטא, סקטור
- ✅ **ציון כניסה 1-10** עם פירוט לכל רכיב + נימוקים בעברית
- ✅ רשימת מעקב (LocalStorage; יוחלף ב-Supabase בפאזה הבאה)
- ✅ עיצוב RTL מלא עם פונט Heebo

## מה דחוי לפאזות הבאות
- 🚧 זיהוי תבנית **Cup &amp; Handle** + תבניות קלאסיות נוספות
- 🚧 כלי שרטוט על הגרף — קווי מגמה ופיבונאצ'י
- 🚧 מודל DCF להערכת שווי + קורלציה למדדים מאקרו (SPY, QQQ, IWM)
- 🚧 ניתוח **סנטימנט** באמצעות Claude Haiku (חדשות) ו-Sonnet (דוחות כספיים)
- 🚧 חישוב **R:R** וגודל פוזיציה (Position Sizing) על בסיס ATR
- 🚧 **Backtesting** לאסטרטגיות
- 🚧 מערכת **התרעות** (מחיר/RSI/ציון) — schema מוכן ב-`supabase/migrations`
- 🚧 אימות משתמשים ב-Supabase Auth

---

## דרישות מערכת (תתקין בעצמך)

1. **Node.js 20+** — https://nodejs.org/
2. **Python 3.11+** — https://www.python.org/downloads/
3. (אופציונלי לפאזה הבאה) **Supabase CLI** — `npm i -g supabase`

> משתמש מסתמך על התקנת תוכנה ידנית — לא יורצו פקודות `winget` אוטומטיות.

## הרצה מקומית

### 1) Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

בדיקה: פתח http://localhost:8000/api/quote?symbol=AAPL — אמור להחזיר JSON עם המחיר.

### 2) Frontend (Next.js)

חלון PowerShell שני:

```powershell
copy .env.local.example .env.local
npm install
npm run dev
```

פתח את http://localhost:3000

חפש סימול (לדוגמה `NVDA`) → קבל גרף, אינדיקטורים, פונדמנטלס וציון 1-10.

---

## פריסה לענן (Production)

### Frontend → Vercel
1. `npm i -g vercel`
2. `vercel` (לחיבור הפרויקט)
3. ב-Vercel → Project Settings → Environment Variables:
   - `NEXT_PUBLIC_API_URL` = כתובת ה-backend (Railway/Render)
   - (פאזה 2) `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`

### Backend → Railway או Render
- צור פרויקט חדש, חבר את התיקייה `backend/`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **חשוב**: ב-`backend/main.py` להחליף `allow_origins=["*"]` בדומיין של Vercel.

### Database → Supabase
1. צור פרויקט חדש ב-https://supabase.com/dashboard
2. SQL Editor → הדבק את `supabase/migrations/0001_initial.sql` → Run
3. Settings → API → העתק `URL` ו-`anon key` ל-`.env.local`

---

## מבנה התיקיות

```
stock-analyst/
├── app/                          # Next.js App Router
│   ├── layout.tsx                # RTL עברית + Heebo
│   ├── page.tsx                  # דשבורד + חיפוש + רשימת מעקב
│   ├── globals.css
│   └── stock/[symbol]/
│       ├── page.tsx              # עמוד ניתוח מניה
│       └── loading.tsx           # שלד טעינה
├── components/
│   ├── Card.tsx
│   ├── StockSearch.tsx
│   ├── Watchlist.tsx
│   ├── WatchlistButton.tsx
│   ├── PriceChart.tsx            # lightweight-charts + MAs + נפח
│   ├── IndicatorPanel.tsx        # MA/RSI/ATR
│   ├── FundamentalsPanel.tsx     # P/E, P/B, ביטא…
│   ├── ScoreDisplay.tsx          # ציון 1-10 + breakdown + נימוקים
│   └── QuoteHeader.tsx
├── lib/
│   ├── api.ts                    # client → FastAPI
│   ├── types.ts                  # מודלים משותפים
│   ├── format.ts                 # פורמט מספרים/אחוזים
│   ├── watchlist.ts              # LocalStorage
│   └── cn.ts
├── backend/                      # שירות Python נפרד
│   ├── main.py                   # FastAPI app
│   ├── indicators.py             # SMA / RSI / ATR (pandas טהור)
│   ├── scoring.py                # ציון 1-10 עם פירוק רכיבים
│   ├── requirements.txt
│   └── README.md
├── supabase/migrations/
│   └── 0001_initial.sql          # watchlist, analysis_history, alerts, news+pgvector
├── .env.local.example
├── package.json
├── next.config.mjs
├── tailwind.config.ts
└── tsconfig.json
```

## נוסחת הציון (תקציר)

```
score = 0.30·trend + 0.20·momentum + 0.15·volatility + 0.15·volume + 0.20·fundamentals
```

- **trend** — יישור MAs (מחיר מעל 20/50/150/200, בונוס על stacking שורי)
- **momentum** — RSI(14) ב-sweet spot 45-65
- **volatility** — ATR% מהמחיר — נמוך יותר → סטופ צמוד → R:R טוב יותר
- **volume** — ממוצע 5 ימים מול ממוצע 50 ימים
- **fundamentals** — P/E, P/B, |ביטא| בטווח 0.7-1.3

הפירוט והנימוקים מוחזרים ל-UI ומוצגים בעברית.

## רישוי
פנימי — לבדיקה אישית.
