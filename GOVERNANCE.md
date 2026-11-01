# JARVIS-OS Governance

JARVIS-OS is an open-source project developed in public. Contributions and good-faith technical disagreement are welcome.

## Roles

- **Maintainer:** the repository owner is currently responsible for releases, repository administration, security coordination, and final decisions when consensus is not reached.
- **Contributor:** anyone who proposes ideas, reports issues, improves documentation, writes tests, or submits code.
- **Reviewer:** a maintainer or invited community member who provides technical feedback. Review feedback does not itself grant repository write access.

Roles may evolve as the community grows. No contributor should assume write access or release authority without an explicit grant.

## Decision-making

1. For substantial changes, start with an issue or proposal describing the problem, goals, constraints, alternatives, and risks.
2. Prefer evidence: reproducible tests, measurements, threat analysis, and documented trade-offs.
3. Seek feedback from affected contributors and subsystem owners where practical.
4. Keep architectural decisions and their rationale in issues, pull requests, or architecture decision records.
5. The maintainer makes the final merge and release decision, explaining significant rejections or requested changes where practical.

Small fixes may go directly through a pull request. Security-sensitive work may use the private process in [SECURITY.md](SECURITY.md).

## Pull-request review

Changes should be focused, testable, documented where needed, and compatible with the project's local-first, evidence-driven, least-privilege, and bounded-autonomy principles. Automated checks are useful but do not replace human review. Contributors should disclose limitations and tests they could not run.

## Community standards

All participation is covered by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Harassment, threats, doxxing, discrimination, and deliberate disruption are not acceptable. Conduct concerns can be reported privately to the repository owner through GitHub.

## License and contributions

The project is licensed under Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). By submitting a contribution for inclusion, contributors agree that it is offered under the project's license, subject to applicable law and any clearly stated third-party terms. Do not submit code or assets you do not have permission to contribute.
