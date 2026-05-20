from __future__ import annotations

import re


# 提取 `at <FQCN>.method(...)` 中的全限定类名,用于折叠摘要
# 兼容 Java 9+ JPMS 格式 `at <module>/<FQCN>.method(...)`:`/` 前的模块名段被跳过
_AT_FQCN_RE = re.compile(r"^\s*at\s+(?:[\w.]+/)?([\w$.]+)\.")


def _summarize_skipped(fqcns: list[str], max_groups: int = 4) -> str:
    """从被折叠的 `at` 帧 FQCN 列表中,按相邻连续相同顶层包合并为摘要片段。

    例:
        ["feign.X", "feign.Y", "org.springframework.aop.A",
         "org.springframework.aop.B", "jdk.proxy3.$Proxy"]
        → "feign.* → org.springframework.* → jdk.proxy3.*"

    顶层包取规则:
    - 单段(如 `feign`):用 `feign.*`
    - 顶级域名根(`org`/`com`/`io`/`net`/`cn`/...):取前 2 段,避免 `org.*` 这种没信息量
    - `jdk.proxy3` / `jdk.internal` 这类二级有区分度:取前 2 段
    - 其他情况只取顶级段(如 `feign.InvocationContext.foo` → `feign`)

    超过 max_groups 段时,中间用 `…` 折叠为首尾两端,例如 `a.* → … → z.*`。
    """
    if not fqcns:
        return ""

    DOMAIN_ROOTS = {"org", "com", "io", "net", "cn", "edu", "gov"}

    def _top(fqcn: str) -> str:
        parts = [p for p in fqcn.split(".") if p]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        head = parts[0]
        # `org.springframework.aop.X` → `org.springframework`,够区分了
        # `com.xxl.job.core.X` → `com.xxl`
        if head in DOMAIN_ROOTS:
            return ".".join(parts[:2])
        # `jdk.proxy3.$Proxy` / `jdk.internal.reflect.X` → 取前 2 段
        if head == "jdk":
            return ".".join(parts[:2])
        # `feign.X.Y` → `feign`,`java.base.X` → `java`
        return head

    # 相邻去重,保留出现顺序
    groups: list[str] = []
    for fqcn in fqcns:
        top = _top(fqcn)
        if not top:
            continue
        if not groups or groups[-1] != top:
            groups.append(top)

    if not groups:
        return ""
    if len(groups) <= max_groups:
        return " → ".join(f"{g}.*" for g in groups)
    return f"{groups[0]}.* → … → {groups[-1]}.*"


def filter_stack(error_message: str, app_prefix: str) -> str:
    """过滤堆栈中的框架噪音行,保留业务代码帧和异常头。

    策略(O(n) 单遍扫描):
    - 业务 `at` 帧(含 app_prefix)原样保留
    - 非业务 `at` 帧累计,在切换回业务帧时输出一行
      `<<< 跳过 N 帧 (pkg1.* → pkg2.* → pkg3.*) >>>` 折叠提示,
      让 LLM 感知被折叠的框架类型(如 feign / spring aop / jdk.proxy)而不只看到数量
    - 异常头、Caused by、Suppressed、日志前缀等非 `at` 行原样保留
    - Python 项目沿用原 site-packages 过滤

    app_prefix 为空时直接返回原文。
    """
    if not app_prefix:
        return error_message

    out: list[str] = []
    skipped_fqcns: list[str] = []  # 收集被折叠帧的 FQCN,用于生成摘要

    def _flush_skip() -> None:
        nonlocal skipped_fqcns
        if skipped_fqcns:
            summary = _summarize_skipped(skipped_fqcns)
            tag = f" ({summary})" if summary else ""
            out.append(f"\t<<< 跳过 {len(skipped_fqcns)} 帧{tag} >>>")
            skipped_fqcns = []

    for line in error_message.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("at "):
            if app_prefix in line:
                _flush_skip()
                out.append(line)
            else:
                m = _AT_FQCN_RE.match(line)
                skipped_fqcns.append(m.group(1) if m else "")
            continue

        if stripped.startswith('File "') and "site-packages" in line and app_prefix not in line:
            skipped_fqcns.append("")
            continue

        _flush_skip()
        out.append(line)

    _flush_skip()
    return "\n".join(out)
