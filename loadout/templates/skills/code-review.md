---
name: {{name}}
description: "Review code changes for correctness, security, readability and test coverage. Use when the user asks for a code review, a PR review, or feedback on a diff."
---

# {{title}}

## When to use
Reviewing a diff, a pull request or a file the user wants a second opinion on.

## Process
1. Read the whole change before commenting; understand the intent first.
2. Look for, in this order: bugs and edge cases, security problems, missing error handling, missing or weak tests, then readability.
3. Run the tests or linters if they are available.

## Output format
- **Summary:** one or two sentences on what the change does.
- **Must fix:** issues that are wrong or unsafe, each with file, line and a suggested fix.
- **Should consider:** improvements that are not blocking.
- **Nitpicks:** style only, kept short.

## Principles
- Be specific and kind; explain *why* something is a problem.
- Do not rewrite code that works just because you would write it differently.
- Say explicitly when you did not review something.
