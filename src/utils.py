from __future__ import annotations


def filter_stack(error_message: str, app_prefix: str) -> str:
    """过滤堆栈中的框架噪音行，只保留业务代码帧和异常头。

    支持 Java（`\tat ...`）和 Python（`  File "..."` in site-packages）。
    app_prefix 为空时直接返回原文。
    """
    if not app_prefix:
        return error_message

    kept, total_at, removed_at = [], 0, 0
    for line in error_message.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("at "):
            total_at += 1
            if app_prefix in line:
                kept.append(line)
            else:
                removed_at += 1
                continue
        elif stripped.startswith('File "') and "site-packages" in line and app_prefix not in line:
            removed_at += 1
            continue
        else:
            kept.append(line)

    if removed_at:
        kept.append(f"    ... ({removed_at}/{total_at} 框架堆栈帧已省略)")
    return "\n".join(kept)
