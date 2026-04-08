# Security Policy

MemoryHub is an agent memory component for OpenShift AI. It stores memories
on behalf of users and agents under a scoped, governed model — taking
vulnerability reports seriously is a first-class concern.

## Reporting a Vulnerability

**Please do not file public GitHub issues for security vulnerabilities.**

Report vulnerabilities privately through GitHub's private vulnerability
reporting:

- Go to <https://github.com/rdwj/memory-hub/security/advisories/new>
- Or navigate to the repository **Security** tab → **Report a vulnerability**

If for any reason you cannot use GitHub's reporting flow, open a minimal
public issue asking for a private contact channel (without disclosing
details of the vulnerability).

When reporting, please include:

- A description of the issue and the affected component
  (`sdk`, `memory-hub-mcp`, `memoryhub-auth`, `memoryhub-core`, `memoryhub-ui`,
  or the operator / deploy manifests)
- Steps to reproduce or a minimal proof of concept
- The version or commit SHA you observed the issue on
- The impact you believe the issue has (confidentiality, integrity,
  availability; scoped or cross-tenant)

You should receive an acknowledgement within a few business days. We will
work with you to confirm the issue, assess impact, and coordinate a fix and
disclosure timeline.

## Supported Versions

MemoryHub is pre-1.0 and under active development. Fixes are applied to
`main`; only the latest release of each published package receives security
updates:

| Package          | Supported                  |
| ---------------- | -------------------------- |
| `memoryhub` (SDK) | Latest release on PyPI     |
| `memory-hub-mcp` | Latest deployed revision   |
| `memoryhub-auth` | Latest deployed revision   |
| Others           | `main` branch only         |

## Scope

In scope:

- Authentication and authorization bypass
- Tenant isolation violations (cross-scope memory access)
- Credential or token leakage
- Injection vulnerabilities in MCP tools, SDK, CLI, or the auth server
- Container or deployment misconfigurations that weaken FIPS or compliance
  posture

Out of scope:

- Findings that require compromising the underlying OpenShift cluster or
  PostgreSQL instance
- Denial-of-service via resource exhaustion against unauthenticated endpoints
  (rate limiting is a deployment concern)
- Issues only reproducible against example or scaffold code in `demos/` or
  `research/`
- Best-practice recommendations without a demonstrated impact

## Disclosure

We prefer coordinated disclosure. Once a fix is available, we will credit the
reporter (unless anonymity is requested) in the release notes and any
GitHub Security Advisory published for the issue.
