---
name: {{name}}
description: "Write clear commit messages and split changes into logical commits. Use when the user asks to commit, to write a commit message, or to clean up history."
---

# {{title}}

## Steps
1. Inspect the staged and unstaged changes.
2. If they mix unrelated concerns, propose how to split them into separate commits.
3. Write the message: a short imperative subject (max ~50 chars), a blank line, then a body explaining *what* and *why*.

## Conventions
- Subject in the imperative: "Add retry to uploader", not "Added" or "Adds".
- Reference the issue or ticket when there is one.
- Never commit secrets, generated files or unrelated formatting changes.
