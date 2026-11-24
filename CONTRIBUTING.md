# Contributing

Thanks for helping. Bug reports, call log lines from your phone system, documentation fixes and code are all welcome.

By taking part you agree to the [code of conduct](CODE_OF_CONDUCT.md).

## Reporting

- **Bugs:** use the [bug report form](https://github.com/olliemaller/ha-nec-pbx/issues/new/choose). Attach diagnostics from the integration's ⋮ menu; phone numbers are masked.
- **A call read wrongly:** use the call log line form, with the `last_raw_line` from your diagnostics. This is one of the most useful things you can do.
- **Security problems:** don't open an issue. See the [security policy](SECURITY.md).
- **Ideas:** open an issue describing what you're trying to do, before writing code, so we can agree on the approach.

## Code

### Set up

```bash
git clone https://github.com/olliemaller/ha-nec-pbx
cd ha-nec-pbx
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt ruff mypy
pip install aionecpbx==0.2.2
pytest
ruff check . && ruff format --check .
```

The SMDR parser and the phone system and FreePBX clients are in [aionecpbx](https://github.com/olliemaller/aionecpbx). A change to how lines are read belongs there. More in [Development](docs/Development.md).

### Ground rules

This talks to people's real phone systems, so a few rules are firm:

- **Be gentle with the phone system.** It has only one SMDR connection. Never open an extra one while the integration is running, and never retry a rejected FreePBX login.
- **Keep callers private.** Phone numbers stay out of logs above debug level, and are masked in diagnostics. Never log the FreePBX secret.
- **No new Python requirements** beyond aionecpbx unless there's no other way.
- **Test it.** Add tests against the fake phone system and fake FreePBX in `tests/` for every change in behaviour. If you can, try it on a real phone system and say which in the pull request.

### Style

- `ruff check .` and `ruff format --check .` pass, and `mypy --strict` is clean. The rules are in `pyproject.toml` and the checks.
- Support every Home Assistant version from the minimum in `hacs.json` to the current beta. Feature-detect newer APIs rather than requiring them.
- User-facing text goes in `strings.json` and `translations/en.json`, in plain, short sentences.
- Documentation is written in Australian English (*colour*, *licence*, *organise*).

### Pull requests

1. Branch from `main`.
2. Keep it to one change, and explain what and why. The pull request template has a checklist.
3. Update the docs in `docs/` and add a line to `CHANGELOG.md` under an `Unreleased` heading.
4. The checks (hassfest, HACS and tests) must pass.

The maintainer handles version numbers and releases.

## Licence

Contributions are licensed under the [MIT licence](LICENSE), the same as the project.
