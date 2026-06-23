# Security policy

Thanks for reporting security issues responsibly. This page explains how to reach the
maintainer privately and what to expect.

## Which versions get fixes

robotframework-falsegreen is in its first development cycle. Security fixes land on the latest
commit on `main`. There is no long-term support branch yet.

| Version | Supported |
|---------|-----------|
| `main`  | yes |
| tagged releases below the latest | no |

## Attack surface

The scanner reads `.robot` and `.resource` files and parses them with the official Robot
Framework parser (`robot.api.get_model`). It does **not** import keyword libraries, start
a browser, or run the suite, so a malicious test file cannot execute through the scanner
alone. The realistic concerns are narrow: a crafted file that makes the parser hang or
crash, and the file-discovery walk following a symlink outside the scanned tree. Reports
in those areas are welcome.

One dependency carries its own surface: `robotframework` itself. A parser bug there
reaches us through `get_model`. If the issue is in the parser, report it upstream too.

## How to report a vulnerability

Do **not** open a public GitHub issue for security problems. Use a private channel:

- **GitHub Security Advisories (preferred):** <https://github.com/vinicq/robotframework-falsegreen/security/advisories/new>
- **Email:** `vinicq@gmail.com` with the subject prefix `[robotframework-falsegreen security]`.

Include a short description and impact, steps to reproduce (ideally a minimal `.robot`
file), the commit SHA or version tested, and whether it has been disclosed elsewhere.

## What to expect

- An acknowledgement within five business days.
- A reproduction or follow-up within ten business days.
- A fix or a clear "won't fix" rationale before any public disclosure.
- Credit in the release notes if you want it.

## What is not a security issue

File these as regular issues: a false positive or false negative (the scanner is
heuristic), slowness on a very large suite, or a finding you disagree with on style grounds.
