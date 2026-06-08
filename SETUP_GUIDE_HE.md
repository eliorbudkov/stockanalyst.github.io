# מדריך הפעלה קצר — הגנת סיסמה

המטרה: להפעיל את האתר עם סיסמה אחת. הסיסמה נקבעת בשרת בלבד, ואתה מקליד אותה
פעם אחת בכניסה לאתר.

הסדר חשוב: קודם מגדירים את המשתנים, ורק בסוף מעלים את הקוד לאוויר.

---

## שלב 1 — סיסמה בשרת הנתונים (Render)

1. היכנס ל-Render ובחר את השירות של הפרויקט.
2. בתפריט הצד לחץ על **Environment**.
3. לחץ **Add Environment Variable** והוסף:

   | שדה Key | שדה Value |
   |---|---|
   | `APP_PASSWORD` | הסיסמה שבחרת |
   | `ALLOWED_ORIGINS` | כתובת האתר שלך ב-Vercel |

   דוגמה לכתובת ב-Value של `ALLOWED_ORIGINS`:

   ```text
   https://your-project.vercel.app
   ```

4. לחץ **Save Changes**. Render יפרוס מחדש אוטומטית.

> רק אם תרצה שכפתור "סרוק עכשיו" יעבוד — הוסף משתנה נוסף בשם
> `GH_DISPATCH_TOKEN` (ההסבר איך מייצרים אותו נמצא בתחתית המדריך).

---

## שלב 2 — הגדרות באתר (Vercel)

1. היכנס ל-Vercel ובחר את הפרויקט.
2. **Settings → Environment Variables**.
3. הוסף את שני המשתנים האלה, וסמן עבור כל אחד גם **Production** וגם **Preview**:

   ```text
   NEXT_PUBLIC_API_URL = https://stockanalyst-github-io.onrender.com
   NEXT_PUBLIC_AUTH_IDLE_MINUTES = 30
   ```

4. שמור.

> אם הגדרת בעבר משתני Supabase (כמו `SUPABASE_URL` או `NEXT_PUBLIC_SUPABASE_URL`) —
> אפשר למחוק אותם. הם כבר לא בשימוש.

---

## שלב 3 — העלאה לאוויר

כשתסיים את שלבים 1–2, כתוב לי כאן **"דחוף"**.
אני אדחוף את הקוד ל-GitHub, וזה יפעיל פריסה אוטומטית גם ב-Vercel וגם ב-Render.

---

## שלב 4 — בדיקה שהכול עובד

1. פתח את כתובת האתר בדפדפן — הוא אמור להעביר אותך אוטומטית לעמוד הכניסה.
2. הקלד את הסיסמה — אתה אמור להגיע לדשבורד.
3. נסה סיסמה שגויה — לא אמורים להיכנס.

אם ההתחברות הראשונה לוקחת עד דקה — זה נורמלי, השרת מתעורר משינה.

---

## איפה מוצאים את כתובת ה-Vercel?

ב-Vercel, במסך הפרויקט (Project → Domains), מופיעה הכתובת — בדרך כלל בסגנון
`https://שם-הפרויקט.vercel.app`. זו הכתובת שתשים ב-`ALLOWED_ORIGINS` בשלב 1.

---

## נספח (אופציונלי) — יצירת מפתח לכפתור הסריקה

נדרש רק אם תרצה שכפתור "סרוק עכשיו" יריץ סריקה אמיתית.

1. ב-GitHub: **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
2. תחת **Repository access** בחר את המאגר של הפרויקט.
3. תחת **Permissions → Repository permissions → Actions** בחר **Read and write**.
4. צור את המפתח והעתק אותו.
5. הדבק אותו ב-Render כערך של המשתנה `GH_DISPATCH_TOKEN`.

המפתח הזה הוא סוד — שמור אותו רק ב-Render, לא בקוד.
