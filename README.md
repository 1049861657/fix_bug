# fix-bug

自动化 Bug 修复工具：接收报错日志 → 创建分支 → AI 修复 → 验证测试 → 推送 PR → 生成报告。

支持 **Python**（pytest）和 **Java / Spring Boot**（Maven，多模块自动识别）项目，平台兼容 GitHub 与 GitLab（含企业自部署）。

## 特性

- **多模块自动识别**：从报错堆栈定位 Maven 模块，自动注入 `-pl <module> -am`，无需手填
- **测试统一隔离**：AI 生成的测试集中到 `<module>/src/test/java/autofix/`，便于审查
- **窄化验证**：Step 3 只跑 AI 本轮新增的测试类，绕开仓库历史脏测试
- **根因优先**：prompt 强制 `[root-cause]` 修复路径，`[mitigation]` 设三重门槛防止偷懒
- **commit 标签**：所有提交带 `[auto] [root-cause]` / `[auto] [mitigation]` 标签，PR 一眼可分
- **堆栈降噪**：业务帧之间的框架链折叠为 `<<< 跳过 N 帧 >>>` 标记
- **Web UI**：浏览器粘贴/上传报错日志即可触发

## 快速开始

### 1. 安装

```bash
uv sync
uv pip install -e .

# 安装 aider（需要 Python 3.13）
uv tool install aider-chat --python 3.13 --with audioop-lts
```

### 2. 配置

**`aider.yaml`** —— 全局 AI 模型配置（所有项目共用）：

```yaml
model: "claude-opus-4.7"
api_base: "https://your-api-gateway/v1"
api_key: "your-api-key"
context_tokens: 200000
```

**`config/<project>.yaml`** —— 每个目标项目一份：

```yaml
type: java
git:
  repo_url: "https://github.com/your-org/your-app"
  clone_base_dir: "D:\\fixRepo"
  base_branch: "main"
  platform: github            # 或 gitlab
  github_token: "ghp_xxx"     # 或 gitlab_token
test:
  cmd: "mvn install -DskipTests -q --no-transfer-progress && mvn test -Dtest=FixBug_* -DfailIfNoTests=false -q --no-transfer-progress"
  framework: "JUnit 5"
  stack_filter: "com.yourorg"   # 业务包前缀，强烈建议填
```

Python 项目示例见 [config/python.yaml](config/python.yaml)，Java 多模块示例见 [config/webportal-bug.yaml](config/webportal-bug.yaml)。

### 3. 运行

```bash
# CLI 模式（推荐）
fix-bug run -c config/your-project.yaml -f error.log

# 直接传入报错字符串
fix-bug run -c config/your-project.yaml -m "NullPointerException at Foo.java:42"

# 本地修复，不推送不建 PR
fix-bug run -c config/your-project.yaml -f error.log --dry-run

# Web UI（浏览器可视化）
fix-bug web --host 0.0.0.0 --port 8000
```

## 流程说明

```
输入报错信息（-f / -m / Web UI 粘贴）
  │
  ├─ filter_stack: 业务帧保留 + 框架帧折叠为 <<< 跳过 N 帧 >>>
  ├─ resolve_module: 从堆栈 FQCN 定位 Maven 模块 → 自动 -pl/-am
  │
  ├─ [Step 1] clone（若不存在）+ 写 .aiderignore → 创建 fix/auto-{timestamp}
  │
  ├─ [Step 2] Aider 修复
  │     · prompt 强制根因路径；找不到根因要走严格 [mitigation] 流程
  │     · 测试统一写入 <module>/src/test/java/autofix/，命名 FixBug_*
  │     · --auto-test 循环：改代码 → 跑测试 → 失败再改
  │
  ├─ [Step 3] 窄化验证：基于 git diff 提取新增测试类，只跑这些
  │
  ├─ [Step 4] 有新提交才推送（避免空 PR）
  ├─ [Step 5] 创建 GitHub PR / GitLab MR
  └─ [Step 6] 生成 Markdown 报告（reports/<repo>/report-{timestamp}.md）
```

## 配置字段速查

### `aider.yaml`（全局）

| 字段 | 说明 |
|---|---|
| `model` | AI 模型名，自动加 `openai/` 前缀 |
| `api_base` / `api_key` | OpenAI 兼容协议端点 |
| `context_tokens` | 模型上下文窗口（默认 200000） |

### `config/<project>.yaml`（项目）

| 字段 | 说明 |
|---|---|
| `type` | `python` / `java`，决定测试默认值 |
| `git.repo_url` | 目标仓库地址，工具自动 clone |
| `git.clone_base_dir` | 本地 clone 根目录 |
| `git.base_branch` | 基准分支（默认 `main`） |
| `git.platform` | `github` / `gitlab` |
| `git.github_token` / `gitlab_token` | 平台访问令牌 |
| `git.git_proxy` | 仅 GitHub 等外网仓库需要 |
| `test.cmd` | 测试命令；多模块仓库无需写 `-pl`，工具自动注入 |
| `test.framework` | `pytest` / `JUnit 5`，用于 prompt 提示 |
| `test.stack_filter` | 业务包前缀（如 `com.yourorg`），用于堆栈过滤与模块定位 |
| `test.dir` | 可选；多模块仓库会自动推导为 `<module>/src/test/java/autofix/` |
| `test.cmd_dir` | 可选；测试命令执行的子目录 |

## 多模块项目支持

工具会自动：
1. **扫描** `*/src/main/java/` 列出所有 Maven 模块
2. **解析堆栈** 提取业务类 FQCN（同时支持标准堆栈 `at com.x.Y...` 和日志格式 `com.x.Y.method:N`）
3. **文件存在性反查** —— 哪个模块的 `src/main/java/<FQCN>.java` 真实存在，就用哪个
4. **差异化注入**：`install` 段加 `-pl <module> -am`，`test` 段只加 `-pl <module>`（避免依赖模块跑 surefire）

支持的堆栈格式示例：
```
at com.foo.Bar.method(Bar.java:42)             ← Java 标准堆栈
[ERROR] com.foo.Bar.method:42 - 业务消息       ← logback / log4j logger 格式
```

## Commit 标签约定

所有自动提交带显式标签：
- `[auto] [root-cause] fix: ...` —— 已定位并修复根因
- `[auto] [mitigation] fix: ...` —— 仅止血，代码里附带 `// TODO(autofix): ...` 注释

GitLab/GitHub 列表里搜 `[mitigation]` 可直接列出所有待跟进的"技术债 PR"。

## 环境变量（可选 `.env`）

```env
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```

Token / API Key 直接写在 yaml 里即可，也可通过环境变量替换。

## 调试与排查

- 日志：`reports/logs/<job_id>.log`（Web UI）或终端输出（CLI）
- 报告：`reports/<repo_name>/report-{timestamp}.md`
- 仓库本地副本：`<clone_base_dir>/<repo_name>/`
- Aider repo-map 缓存：仓库根的 `.aider.tags.cache.v4/`（可清除强制重建）
