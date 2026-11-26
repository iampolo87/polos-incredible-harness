# Security & Deployment

## Input & Output
- Validate all inputs at system boundaries (type, range, format)
- Use parameterized queries / prepared statements — never concatenate user input into SQL
- Escape output contextually (HTML, JS, URL, CSS) to prevent XSS
- Use CSRF tokens on state-changing requests

## Authentication & Authorization
- Hash passwords with bcrypt/argon2 — never MD5/SHA1
- Use secure session configuration (httpOnly, secure, sameSite)
- Apply least-privilege principle to roles and permissions
- Implement rate limiting on authentication endpoints

## Secrets & Credentials
- Never hardcode credentials — use environment variables or vault services
- Rotate secrets periodically; never commit .env files
- Use separate credentials per environment (dev/staging/prod)

## Error Handling
- Handle errors gracefully without exposing internals (stack traces, DB structure)
- Log security events (failed logins, permission denials, input violations)
- Return generic error messages to users; log detailed errors server-side

## Dependencies & Headers
- Keep dependencies updated — audit regularly for known vulnerabilities
- Set security headers: Content-Security-Policy, X-Content-Type-Options, Strict-Transport-Security, X-Frame-Options

## Deployment
- Use CI/CD pipelines, automated testing, staging environments
- Monitor performance and behaviour post-deployment — logging, metrics, alerts
- Disable debug mode and development tools in production
