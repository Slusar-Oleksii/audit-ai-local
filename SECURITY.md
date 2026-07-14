# Security Policy

## Supported version

Security fixes are applied to the latest revision of the `main` branch.

## Reporting a vulnerability

Please use GitHub's **Report a vulnerability** flow in the repository Security
tab. Do not include confidential documents, credentials, personal data, or a
working exploit in a public issue.

Include the affected file or component, impact, reproduction preconditions,
and a minimal proof that does not expose real audit data. Maintainers will
acknowledge a report when it has been reviewed.

## Deployment boundary

AUDIT AI is a single-user local application. Streamlit must remain bound to
`127.0.0.1`; exposing it to a network requires a separate authentication,
authorization, TLS, and deployment-security design.
