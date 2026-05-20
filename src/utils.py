from __future__ import annotations


def filter_stack(error_message: str, app_prefix: str) -> str:
    """过滤堆栈中的框架噪音行，保留业务代码帧和异常头。

    策略（O(n) 单遍扫描）：
    - 业务 `at` 帧（含 app_prefix）原样保留
    - 非业务 `at` 帧累计，在切换回业务帧时输出一行 `... 跳过 N 帧 ...` 折叠提示，
      让 LLM 感知到中间存在框架链而不必看具体内容
    - 异常头、Caused by、Suppressed、日志前缀等非 `at` 行原样保留
    - Python 项目沿用原 site-packages 过滤

    app_prefix 为空时直接返回原文。
    """
    if not app_prefix:
        return error_message

    out: list[str] = []
    skipped_run = 0

    def _flush_skip() -> None:
        nonlocal skipped_run
        if skipped_run > 0:
            out.append(f"\t<<< 跳过 {skipped_run} 帧 >>>")
            skipped_run = 0

    for line in error_message.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("at "):
            if app_prefix in line:
                _flush_skip()
                out.append(line)
            else:
                skipped_run += 1
            continue

        if stripped.startswith('File "') and "site-packages" in line and app_prefix not in line:
            skipped_run += 1
            continue

        _flush_skip()
        out.append(line)

    _flush_skip()
    return "\n".join(out)
