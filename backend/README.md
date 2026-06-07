# Stock Analyst — Backend (FastAPI)

שירות Python שמספק נתוני מניות (yfinance), אינדיקטורים טכניים וחישוב ציון 1-10.

## הרצה מקומית (Windows / PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

ה-API ירוץ ב-http://localhost:8000

## נקודות קצה

- `GET /api/quote?symbol=AAPL` — מחיר נוכחי + פונדמנטלס בסיסי
- `GET /api/history?symbol=AAPL&period=2y` — נרות יומיים (OHLCV)
- `GET /api/analyze?symbol=AAPL&period=2y` — ניתוח מלא + ציון 1-10

## הערות

- `yfinance` היא ספרייה לא-רשמית. עלולה להישבר בעת שינויים ב-Yahoo. ל-production עדיף API בתשלום (Polygon).
- אין כאן rate limiting / cache. בעתיד: להוסיף Redis cache + per-IP throttling.
- בעת פריסה ל-production (Railway / Render / Fly):
  - להגדיר משתנה `ALLOWED_ORIGINS` ולהחליף את `allow_origins=["*"]` ב-`main.py`
  - להגדיר את `NEXT_PUBLIC_API_URL` ב-Vercel לכתובת ה-backend
