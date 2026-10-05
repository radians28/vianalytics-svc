from datetime import date, timedelta


def _anchor(year: int) -> date:
    """Saturday on or before Jan 1 of the given year (start of Period 1)."""
    jan1 = date(year, 1, 1)
    # Python weekday(): Mon=0 ... Sat=5 ... Sun=6
    return jan1 - timedelta(days=(jan1.weekday() - 5) % 7)


def generate_periods(year: int) -> list[dict]:
    """
    Return the 13 periods of `year` as a list of dicts:
      {"period": int, "start_date": YYYYMMDD int, "end_date": YYYYMMDD int}

    Rules:
      - Week = Saturday..Friday.
      - Period 1 starts on the Saturday on or before Jan 1 (clipped to Jan 1).
      - Periods 1-12 are 4 weeks (28 days) each.
      - Period 13 starts right after Period 12 and always ends on Dec 31.
    """
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    start = _anchor(year)

    to_int = lambda d: int(d.strftime("%Y%m%d"))
    result = []

    for p in range(1, 14):
        end = year_end if p == 13 else start + timedelta(days=27)

        result.append({
            "period": p,
            "start_date": to_int(max(start, year_start)),
            "end_date": to_int(end),
        })
        start = end + timedelta(days=1)

    return result