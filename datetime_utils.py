from datetime import datetime, timedelta, timezone

def time_before(target):
    now = datetime.now(timezone(timedelta(hours=5)))
    delta = target - now

    if delta.total_seconds() > 0:
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}:{hours:02}:{minutes:02}:{seconds:02}"
    else:
        return "0:00:00:00"

def get_day_word(n):
    if 11 <= n % 100 <= 14:
        return "дней"
    last_digit = n % 10
    if last_digit == 1:
        return "день"
    if 2 <= last_digit <= 4:
        return "дня"
    return "дней"

def days_passed_since(target):
    from datetime import datetime

    now = datetime.now(timezone(timedelta(hours=5)))
    delta = now - target
    days = delta.days
    if days < 0:
        days = 0
    return f"{days} {get_day_word(days)}"

def days_before(target):
    from datetime import datetime

    now = datetime.now(timezone(timedelta(hours=5)))
    delta = target - now
    days = delta.days + 1
    if days < 0:
        days = 0
    return f"{days} {get_day_word(days)}"
