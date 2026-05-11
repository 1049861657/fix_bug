def format_currency(amount: float, symbol: str = "¥") -> str:
    """格式化金额显示"""
    return f"{symbol}{amount:.2f}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    """将值限制在 [min_val, max_val] 范围内"""
    return max(min_val, min(max_val, value))    # bug: max/min 顺序错误，应为 min(max_val, max(min_val, value))


def percentage_of(part: float, total: float) -> float:
    """计算 part 占 total 的百分比"""
    if total == 0:
        raise ZeroDivisionError("总量不能为零")
    return (part / total) * 100
