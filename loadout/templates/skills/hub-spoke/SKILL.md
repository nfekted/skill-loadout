---
name: {{name}}
description: "Orchestrator for a multi-step workflow split into modules. Use when the task needs the analyze, implement and verify phases described in this skill."
---

# {{title}}

This skill is an **orchestrator**. It only decides which step comes next; the details live in `modules/`.

## On-demand reading
Do **not** load every module at once. Read only the module for the step you are currently executing, and nothing else.

## Flow
1. **Analyze** — read `modules/01-analyze.md`. Understand the request and the context.
2. **Implement** — read `modules/02-implement.md`. Make the change.
3. **Verify** — read `modules/03-verify.md`. Prove the result is right before finishing.

If verification fails, go back to the step that caused the problem.
