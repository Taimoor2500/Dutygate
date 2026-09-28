# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Report them privately through
GitHub: go to the repository's **Security** tab, choose **Report a vulnerability**, and include
steps to reproduce.

We aim to acknowledge reports within 3 business days and to agree a fix and disclosure
timeline with you.

## In scope

- anything that makes the gate silently return `continue` for a message it should flag, or
  drop a message (fail-open bugs)
- leaking message text or API keys through logs, errors, metrics or audit files
- sidecar authentication bypasses
- redaction bypasses in the reference packs
- denial of service through crafted messages (for example, regex backtracking)

## Out of scope

- The detection quality of a pack on messages it was never tuned for. Please open a normal
  issue with an example instead.
- Prompt-injection attempts that change TypeSafe's scores. This is a documented risk (see
  `docs/privacy.md`); reports that come with a reproducible dataset row are still very welcome
  as normal issues.

## Supported versions

Only the latest release receives security fixes during 0.x.
