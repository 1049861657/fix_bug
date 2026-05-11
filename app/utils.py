def format_currency(amount: float, symbol: str = "¥") -> str:
    return f"{symbol}{amount:.2f}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    return min(max_val, max(min_val, value))


def percentage_of(part: float, total: float) -> float:
    if total == 0:
        raise ZeroDivisionError("总量不能为零")
    return (part / total) * 100
