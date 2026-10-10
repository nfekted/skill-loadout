# Security basics

- Never hard-code secrets; read them from environment variables or a secret store.
- Validate and sanitize all external input before using it in queries, commands, paths or HTML.
- Use parameterized queries; never build SQL with string concatenation.
- Prefer well-maintained libraries over custom cryptography.
- Do not log sensitive data (tokens, passwords, personal information).
- Apply the principle of least privilege to permissions, tokens and file access.
