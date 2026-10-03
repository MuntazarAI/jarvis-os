## Summary

<!-- What changed and why? Link issues where applicable. -->

## Validation

- [ ] Tests added or updated where appropriate
- [ ] Relevant tests pass locally (`pytest -q`)
- [ ] `python -m compileall -q jarvis` clean
- [ ] `jarvis doctor` checked (if behavior-affecting)
- [ ] Documentation updated if needed
- [ ] Security/privacy implications considered
- [ ] No unrelated changes included
- [ ] No secrets in diff (`git diff` reviewed)

## Safety

- [ ] No policy/auth bypass
- [ ] No new persistence of raw audio, secrets, or credentials
- [ ] Deterministic tests only (no network/mic/GPU unless marked manual)

## Notes

<!-- Limitations or checks that could not be run. -->
