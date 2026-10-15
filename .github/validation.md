# Repository validation

Protected default branch: pull requests, three approvals, no deletion/force pushes and automatic Copilot review on new pushes (excluding drafts).

- Project check: **Validate infrastructure configuration**.
- Secret scan: Gitleaks, redacted output.


Checks become required after a successful bootstrap PR run. Existing required checks are preserved. New workflow files require merging this PR to run on subsequent PRs. No paid code-quality service is enabled by this change.

Structured-file and source syntax validation does not execute the application, contact databases or call AI models. Repositories without source code do not have application/unit tests yet.
