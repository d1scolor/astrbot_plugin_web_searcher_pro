# Project instructions

- This is a public fork. Never commit real endpoints, tokens, diagnostic exports,
  private user content or deployment configuration.
- Never use SSH keys to access another machine without explicit authorization.
- Do not dump container environments or secret-bearing configuration.
- Use uv for Python development and dependency management.
- Keep Prompt Guard optional. When enabled, all external text-return paths must
  fail closed before any original content reaches the LLM if screening fails.
- Public HTTP requests must reject private/local addresses at connection time and
  across redirects. Trusted infrastructure exceptions are administrator-configured,
  endpoint-scoped and must never be selectable through tool arguments.
- Chat commands must not change global AstrBot settings or enable unrelated tools.
- Image search returns bounded metadata only; do not add automatic candidate downloads.
- Preserve upstream attribution and distinguish mock tests from deployment validation.
