from datetime import date, datetime


def stamp_mmddyy() -> str:
    return datetime.now().strftime("%m-%d-%y")


def stamp_yyyymmdd() -> str:
    return datetime.now().strftime("%Y_%m_%d")


def compute_current_term_code(today: date | None = None) -> str:
    if today is None:
        today = date.today()

    y = today.year
    m = today.month
    d = today.day

    # Spring
    if (
        m in (1, 2, 3, 4)
        or (m == 5 and d <= 15)
    ):
        return f"{y}30"

    # Summer
    if (
        (m == 5 and d >= 16)
        or m in (6, 7)
        or (m == 8 and d <= 15)
    ):
        return f"{y + 1}10"

    # Fall
    return f"{y + 1}20"


def compute_future_term_code(today: date | None = None) -> str:
    if today is None:
        today = date.today()

    y = today.year
    m = today.month
    d = today.day

    if (m == 1) or (m == 2 and d <= 15):
        return f"{y}30"

    if (m == 2 and d >= 16) or m in (3, 4, 5):
        return f"{y + 1}10"

    if m in (6, 7, 8):
        return f"{y + 1}20"

    return f"{y + 1}30"