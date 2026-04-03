# Example Middleware

This directory contains reference implementations of MCP middleware.

## What's Here

- **auth_middleware.py** - Authentication and authorization middleware
- **logging_middleware.py** - Request/response logging middleware

## Important Notes

⚠️ **These examples are NOT loaded by the server** - they are in a subdirectory that auto-discovery skips.

💡 **To use an example:**
1. Copy the file to `src/middleware/` (parent directory)
2. Customize it for your needs
3. Auto-discovery will register it automatically

🧹 **To remove all examples:**
```bash
./remove_examples.sh
```

This prevents examples from cluttering your AI assistant's context window.
