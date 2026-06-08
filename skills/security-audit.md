---
name: security-audit
description: Security audit guidance for all project phases
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: true
  architect_reviewer: true
  pm_reviewer: true
tags: [security, auth, jwt, oauth, csrf, injection, xss, secrets, encryption]
source: local
---

# Security Audit Skill

## For Product Managers
- Include security acceptance criteria in the PRD: authentication method, data classification, compliance requirements (GDPR, HIPAA, SOC2 if applicable)
- Identify which data is PII and document retention/deletion requirements
- Specify rate limiting and abuse prevention requirements explicitly

## For PM Reviewers
- Verify security acceptance criteria are specific and testable
- Check that PII handling and data retention are addressed
- Flag missing compliance requirements for regulated industries

## For Architects
- Threat model before finalising design: who are the attackers, what are the assets, what are the attack vectors?
- Apply principle of least privilege: each component/service requests only the permissions it needs
- Never store secrets in code, committed config files, or committed env files. Runtime environment variables are acceptable injection points when backed by a secret manager or deployment secret store
- Plan for secret rotation from day one
- Use short-lived tokens (JWT exp ≤ 15 min) with refresh tokens stored `httpOnly`

## For Architect Reviewers
- Verify the threat model covers OWASP Top 10
- Check that authentication and authorisation are separate concerns
- Flag any design that stores secrets in environment variables without a secrets manager

## For Engineers
- Never log secrets, tokens, passwords, or PII — scrub before logging
- Parameterise all database queries — no string concatenation in SQL
- Validate and sanitise all user input server-side (never trust the client)
- Use `bcrypt` (cost ≥ 12) or `argon2` for password hashing — never MD5/SHA1
- Set security headers: `Content-Security-Policy`, `X-Frame-Options`, `Strict-Transport-Security`

## For Code Reviewers
- Flag any secret, token, or credential that appears in source code
- Reject string-concatenated SQL queries — must use parameterised queries
- Flag missing input validation on any endpoint that accepts user data
- Check that error responses don't leak stack traces or internal details to clients
- Verify `httpOnly` and `Secure` flags on auth cookies

## For QA Engineers
- Run OWASP ZAP baseline scan against the running application
- Test authentication boundary: verify unauthenticated requests to protected endpoints return 401
- Test authorisation: verify user A cannot access user B's resources
- Test for SQL injection on all input fields
- Verify secrets are not present in API responses, logs, or HTML source
