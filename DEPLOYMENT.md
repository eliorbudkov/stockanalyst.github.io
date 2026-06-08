# פריסת Stock Analyst

המערכת משתמשת בארבעה שירותים:

- GitHub שומר את הקוד ומריץ את הסריקה הכבדה.
- Vercel מפעיל את אתר Next.js.
- Render מפעיל את FastAPI.
- Supabase מיועד למסד הנתונים.

## 1. GitHub

המאגר הנוכחי הוא `eliorbudkov/stockanalyst.github.io`.

במאגר פתח:

`Settings -> Actions -> General -> Workflow permissions`

בחר `Read and write permissions`.

ה־workflow נמצא ב־`.github/workflows/refresh-seed.yml`. הוא מופעל בלחיצה על
כפתור הסריקה באתר או ידנית מתוך לשונית Actions.

## 2. GitHub token עבור Render

צור Fine-grained personal access token:

1. פתח `Settings -> Developer settings -> Personal access tokens`.
2. צור Fine-grained token שמוגבל למאגר `eliorbudkov/stockanalyst.github.io`.
3. הגדר הרשאת `Actions: Read and write`.
4. העתק את הטוקן. הוא מוצג פעם אחת בלבד.

אין לשמור את הטוקן בקוד או ב־Vercel.

## 3. Backend ב־Render

אפשר ליצור Blueprint מהקובץ `render.yaml`.

בהגדרה ידנית:

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/`

הגדר ב־Render:

```text
ENABLE_LIVE_SCAN=0
GH_REPO=eliorbudkov/stockanalyst.github.io
GH_WORKFLOW=refresh-seed.yml
GH_REF=main
GH_DISPATCH_TOKEN=<GitHub token>
```

`GH_DISPATCH_TOKEN` הוא סוד של השרת בלבד.

## 4. Frontend ב־Vercel

חבר את אותו מאגר GitHub ל־Vercel והגדר:

```text
NEXT_PUBLIC_API_URL=https://<render-service>.onrender.com
```

אין להוסיף `/` בסוף הכתובת. לאחר שינוי המשתנה יש לבצע Redeploy ב־Vercel.

## 5. בדיקה

1. פתח `https://<render-service>.onrender.com/`.
2. ודא שמתקבל `{"service":"stock-analyst-api","status":"ok"}`.
3. פתח את אתר Vercel וודא שנתוני ה־seed מוצגים.
4. לחץ על כפתור הסריקה.
5. ודא ב־GitHub Actions שה־workflow `Refresh scan seed` התחיל.
6. לאחר סיום ה־workflow, Render יבצע deploy מחדש.
7. האתר יזהה את `fetched_at` החדש ויציג את התוצאה.

הסריקה עשויה להימשך 5 עד 10 דקות. אין להפעיל `ENABLE_LIVE_SCAN=1` ב־Render Free.
