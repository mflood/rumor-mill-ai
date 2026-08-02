# Repository instructions

## GitHub interactions

Use the authenticated `gh` CLI for all GitHub API interactions, including pull requests,
issues, reviews, checks, releases, and repository metadata. Do not use a GitHub connector or
app. Continue to use local `git` commands for branch, commit, and push operations.

## Linear issue workflow

Whenever starting implementation of a new Linear issue:

1. Begin from the repository's `main` branch and pull the latest `origin/main` before making issue-specific changes. Preserve unrelated local work; if switching or pulling would overwrite it, stop and ask the user how to proceed.
2. Create a dedicated feature branch from the updated `main` branch before editing. Use the `codex/` prefix and include the canonical Linear issue identifier and a short description, for example `codex/six-49-simulation-clock`.
3. Implement and validate the issue, then end the task by committing the scoped changes, pushing the feature branch, and opening a ready-for-review (non-draft) pull request. Do not include unrelated working-tree changes.
4. Start the pull-request title with the canonical Linear issue identifier in square brackets, followed by a concise description, for example `[SIX-49] Build the simulation clock and job scheduler`.
