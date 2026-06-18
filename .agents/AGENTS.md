# Shikigen

AI Agent 聊天助手 — 用户与 AI Agent 对话，Agent 可调用工具、流式返回响应。

## 架构

```
apps/web/   →  Next.js 15 (App Router) + Vercel AI SDK (@ai-sdk/react useChat)
apps/api/   →  FastAPI + LangChain DeepAgents + uv
```

- 前端 `useChat` → `/api/chat` → Next.js rewrites 代理到 `localhost:8000`
- 通信协议：SSE（流式）+ HTTP（普通请求）+ HTTP（心跳轮询）

## 常用命令

```bash
pnpm dev          # 同时启动前后端
pnpm dev:web      # 仅前端 (localhost:3000)
pnpm dev:api      # 仅后端 (localhost:8000)
cd apps/api && uv run uvicorn app.main:app --reload --port 8000
```

## 领域文档

单上下文项目：`CONTEXT.md`（术语表）+ `docs/adr/`（架构决策记录）。

---

## Agent skills

### Issue tracker

Issues tracked as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Status: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`, `done`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
