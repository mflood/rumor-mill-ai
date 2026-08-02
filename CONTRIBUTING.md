# Contributing to Rumor Mill AI

Thanks for helping build Rumor Mill AI. Bug reports, documentation, tests, engine improvements,
evaluation cases, and original worlds are welcome.

By participating, you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md). For product and
usage questions, see [Support](SUPPORT.md). Report vulnerabilities according to
[Security](SECURITY.md), not in a public issue.

## Before opening a pull request

1. Search existing issues and pull requests. Open an issue before a large or behavior-changing
   proposal so its scope can be agreed on early.
2. Fork the repository, branch from `main`, and keep each pull request focused on one change.
3. Install the development environment with `make setup`.
4. Add or update tests for behavioral changes. Run `make ci`; it checks formatting, linting, strict
   typing, the deterministic test suite, and narrative evaluations.
5. Update user-facing documentation and `CHANGELOG.md` when the change affects users.

Pull requests should explain the problem and approach, link their issue, identify risks, and list
the exact checks run. Changes to prompts, story logic, world data, or other narrative behavior must
add or update deterministic eval cases when appropriate. If an eval is not applicable, explain why
in the pull-request template.

## World content and generated material

Code and documentation are not the only contributions in this repository. World definitions,
characters, dialogue, lore, images, evaluation fixtures, and other narrative assets may carry
copyright, publicity, privacy, trademark, or contractual rights.

For every contribution, you affirm that:

- you created the contribution or otherwise have the right to submit and license it;
- it does not knowingly copy protected characters, settings, text, images, or other material, and
  it does not misuse a real person's identity or private information;
- you disclose material generated or transformed by an AI system in the pull request, including
  the tool and the human review performed; and
- authored world content includes meaningful human selection, editing, and creative control.

The legal status and ownership of purely machine-generated material can vary by jurisdiction.
Submitting it does not guarantee that anyone owns copyright in it. Maintainers may reject or remove
material whose provenance, consent, originality, or license is unclear. Do not submit confidential
prompts, third-party training data, or output whose service terms do not permit this use.

Unless you state otherwise where a contribution is submitted, you license your contribution under
this repository's [MIT License](LICENSE) and represent that you have authority to do so. This is a
contributor affirmation, not legal advice and not a transfer of ownership.

## Review expectations

Maintainers may request smaller commits, additional tests or evals, provenance details, accessibility
improvements, or documentation. Be patient and constructive. A contribution may be declined when it
does not fit the project direction even if it is technically sound.
