---
status: accepted
---
# Credentials come from the environment only; the token cache is optional and account-bound

The original tool resolved credentials through a specific password manager item as a fallback. hostaway-cli reads the account ID and secret from the environment and nothing else, so it makes no assumption about how an operator stores secrets. The optional token cache keeps the previous safety properties: owner-only file permissions, atomic replace, and a hard stop when the cached account ID differs from the configured one.
