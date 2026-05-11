# fix-bug

自动化 Bug 修复工具：接收报错日志 → 创建分支 → AI 修复 → 验证测试 → 提交 PR → 通知负责人。

## 快速开始

### 1. 安装

```bash
pip install -e .
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 GITHUB_TOKEN、ANTHROPIC_API_KEY 等
# 编辑 config.yaml，填入 repo_slug、test_cmd 等
```

### 3. 使用

```bash
# 方式一：直接传入报错信息
fix-bug run -m "TypeError: 'NoneType' object is not subscriptable at app/service.py:42"

# 方式二：传入日志文件
fix-bug run -f error.log

# 方式三：stdin 管道
cat error.log | fix-bug run

# 不推送/不创建 PR，仅本地修复验证
fix-bug run -f error.log --dry-run
```

## 流程说明

```
用户输入报错 → [Step 1] 从 main 创建 fix/auto-{timestamp} 分支
             → [Step 2] Aider (AI) 分析并修复代码，自动运行测试重试
             → [Step 3] 再次运行测试做最终验证
             → [Step 4] 推送分支到 GitHub
             → [Step 5] 自动创建 Pull Request
             → [Step 6] 钉钉/Slack/企业微信通知负责人
```

## 配置说明

| 字段 | 说明 |
|------|------|
| `git.repo_path` | 目标仓库本地路径 |
| `git.base_branch` | 基准分支，默认 `main` |
| `aider.model` | 使用的 AI 模型 |
| `aider.test_cmd` | 测试命令 |
| `aider.max_retries` | Aider 自动重试次数 |
| `github.repo_slug` | `owner/repo` 格式 |
| `notify[].type` | `dingtalk` / `slack` / `wecom` |
