"""Donald J. Trump securities disclosed in the latest official OGE update.

The May 8, 2026 OGE Form 278-T reports 2026 transactions. Its equity entries
are sales, not evidence of current ownership, so they are retained for
transparency but are not eligible for the scoring bonus.
"""
from __future__ import annotations

from datetime import date
from typing import Any

SOURCE_DATE = date(2026, 5, 8)
SOURCE_URL = (
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS%2BIndex/"
    "405E4EC4E27BE8D185258DF7002DD1C0/%24FILE/"
    "Trump%2C%20Donald%20J.-05.08.2026-278T%282%29.pdf"
)
SOURCE_LABEL = "OGE Form 278-T, filed May 8, 2026"

# These equities were explicitly reported as sales in the latest filing.
# A sale does not establish current ownership and cannot earn a holdings bonus.
TRUMP_HOLDINGS: list[dict[str, Any]] = [
    {"symbol": "PLTR", "name": "Palantir Technologies", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "UNH", "name": "UnitedHealth Group", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "PANW", "name": "Palo Alto Networks", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "NFLX", "name": "Netflix", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "CRM", "name": "Salesforce", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "META", "name": "Meta Platforms", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "RDDT", "name": "Reddit", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "ADBE", "name": "Adobe", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "DIS", "name": "Walt Disney", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
    {"symbol": "ABT", "name": "Abbott Laboratories", "category": "reported_sale", "bonus_eligible": False, "note": "מכירה שדווחה ב-2026"},
]


def source_expires_on(source_date: date = SOURCE_DATE) -> date:
    try:
        return source_date.replace(year=source_date.year + 1)
    except ValueError:
        return source_date.replace(year=source_date.year + 1, day=28)


def is_source_fresh(as_of: date | None = None) -> bool:
    return (as_of or date.today()) <= source_expires_on()


def get_trump_symbols(as_of: date | None = None) -> set[str]:
    """Return bonus-eligible symbols only while the source is fresh."""
    if not is_source_fresh(as_of):
        return set()
    return {
        holding["symbol"].upper()
        for holding in TRUMP_HOLDINGS
        if holding.get("bonus_eligible") is True
    }


def is_trump_held(symbol: str | None, as_of: date | None = None) -> bool:
    if not symbol:
        return False
    return symbol.upper().strip() in get_trump_symbols(as_of)


def get_trump_holdings() -> dict[str, Any]:
    today = date.today()
    fresh = is_source_fresh(today)
    return {
        "holdings": TRUMP_HOLDINGS,
        "last_filing": SOURCE_DATE.isoformat(),
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "bonus_active": fresh and bool(get_trump_symbols(today)),
        "source_fresh": fresh,
        "source_age_days": (today - SOURCE_DATE).days,
        "bonus_suspended_after": source_expires_on().isoformat(),
        "disclaimer": (
            "דוח 278-T מציג עסקאות ולא בהכרח החזקות נוכחיות. "
            "עסקאות מכירה אינן מזכות בבונוס. הבונוס מושעה אוטומטית "
            "כאשר מקור הנתונים ישן מ-12 חודשים."
        ),
    }
