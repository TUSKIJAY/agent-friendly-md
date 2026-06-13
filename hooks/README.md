# Hooks (v1+ 可选增强 — 首期不进关键路径)

MVP 主路径采用**显式 gate**，不依赖 hooks。本目录首期只放说明。

## 原则

```text
gate 是事实裁判，hook 只是提醒和提前拦截。
```

- hooks **不**负责自动修改 `STATE.json`。
- hooks **不**作为 package 的唯一阻断机制。
- review 指出 hooks 与当前工作区已验证模式存在冲突，故推迟到 v1 之后。

## 若未来启用，必须补齐

- 注册位置：项目级还是用户级 settings。
- Windows / PowerShell / bash 兼容策略。
- hook 失效时的降级路径。
- 每个 hook 的单元测试。
- 与显式 gate 的职责边界。

## 候选 hooks

| hook | 作用 |
| --- | --- |
| `inject_job_brief.py` | 提醒当前 phase 和应读文件 |
| `phase_tool_gate.py` | 提前拦截明显越权工具 |
| `post_write_hint.py` | 写入阶段产物后提示运行哪个 gate |
