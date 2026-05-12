# fix-bug

自动化 Bug 修复工具：接收报错日志 → 创建分支 → AI 修复 → 验证测试 → 推送 PR → 生成报告。

支持 **Python**（pytest）和 **Java / Spring Boot**（Maven / Gradle）项目。

## 快速开始

### 1. 安装

```bash
# 安装 fix-bug 工具
uv sync
uv pip install -e .

# 安装 aider（需要 Python 3.13）
uv tool install aider-chat --python 3.13 --with audioop-lts
```

### 2. 配置

```bash
cp .env.example .env
# 填入 FIX_BUG_API_KEY、FIX_BUG_API_BASE、GITHUB_TOKEN
```

按语言复制对应配置文件并填写仓库地址：

```bash
# Python 项目
cp config.yaml my-project.yaml

# Java 项目
cp config-java.yaml my-java-project.yaml
```

### 3. 运行

```bash
# 传入日志文件（推荐）
fix-bug run -f error.log

# 直接传入报错字符串
fix-bug run -m "ArithmeticException: / by zero at TodoServiceImpl.java:99"

# 指定配置文件（默认读 config.yaml）
fix-bug run -c config-java.yaml -f error.log

# 仅本地修复，不推送不创建 PR
fix-bug run -f error.log --dry-run
```

## 流程说明

```
输入报错信息（-f / -m / stdin）
    │
    ├─ [Step 1] 自动 clone 目标仓库（若不存在），从 main 创建 fix/auto-{timestamp} 分支
    │
    ├─ [Step 2] Aider (AI) 分析报错 → 补充测试 → 修复代码 → --auto-test 循环验证
    │
    ├─ [Step 3] 再次独立运行测试做最终确认
    │
    ├─ [Step 4] 推送分支到 GitHub
    │
    ├─ [Step 5] 自动创建 Pull Request
    │
    └─ [Step 6] 生成 Markdown 修复报告（reports/report-{timestamp}.md）
```

## 配置说明

### Python 项目（config.yaml）

```yaml
git:
  repo_url: "https://github.com/your-org/your-python-app"
  clone_base_dir: "D:\\fixRepo"
  base_branch: "main"

aider:
  model: "openai/claude-opus-4.7"
  api_base_env: "FIX_BUG_API_BASE"
  api_key_env: "FIX_BUG_API_KEY"
  test_cmd: "pytest tests/ -x -q"
  test_framework: "pytest"
  test_dir: "tests/"
  context_tokens: 200000

github:
  token_env: "GITHUB_TOKEN"
```

### Java 项目（config-java.yaml）

```yaml
git:
  repo_url: "https://github.com/your-org/your-java-app"
  clone_base_dir: "D:\\fixRepo"
  base_branch: "main"

aider:
  model: "openai/claude-opus-4.7"
  api_base_env: "FIX_BUG_API_BASE"
  api_key_env: "FIX_BUG_API_KEY"
  test_cmd: "mvn test -q --no-transfer-progress"
  cmd_dir: "demo"                  # pom.xml 所在子目录（单模块项目可留空）
  stack_filter: "com.example"      # 应用包名前缀，过滤框架噪音堆栈帧
  test_framework: "JUnit 5"
  test_dir: "demo/src/test/java/"
  context_tokens: 200000

github:
  token_env: "GITHUB_TOKEN"
```

### 关键配置字段

| 字段 | 说明 |
|---|---|
| `git.repo_url` | 目标仓库 GitHub 地址，工具自动 clone |
| `git.clone_base_dir` | 本地 clone 根目录 |
| `git.base_branch` | 基准分支，默认 `main` |
| `aider.model` | AI 模型，格式 `openai/<model-name>` |
| `aider.test_cmd` | 测试命令（在 `cmd_dir` 下执行） |
| `aider.cmd_dir` | 执行测试命令的子目录（Maven 子模块等） |
| `aider.stack_filter` | 应用包名前缀，用于过滤堆栈噪音（Java 推荐填） |
| `aider.test_framework` | 测试框架名称，用于 prompt（`pytest` / `JUnit 5`） |
| `aider.test_dir` | 测试文件目录，告知 AI 在哪里写测试 |
| `aider.context_tokens` | 模型上下文窗口大小 |

## 环境变量（.env）

```env
FIX_BUG_API_BASE=https://your-api-gateway/v1
FIX_BUG_API_KEY=your-api-key
GITHUB_TOKEN=ghp_your_github_token
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```
