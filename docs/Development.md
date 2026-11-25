# Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt ruff mypy
pip install aionecpbx==0.2.3
pytest
ruff check . && ruff format --check .
mypy --strict --implicit-reexport --ignore-missing-imports custom_components/nec_pbx
```

Since 0.7.0 the SMDR parser and the phone system and FreePBX clients live in their own library, [aionecpbx](https://github.com/olliemaller/aionecpbx). Install the version pinned in `custom_components/nec_pbx/manifest.json`. To work on both at once, clone aionecpbx next to this repository and install it editable instead:

```bash
pip install -e ../aionecpbx
```

The tests include a fake phone system: a TCP server that sends SMDR lines, splits them across packets and drops the connection, so the whole integration is tested end to end.

## Adding a new SMDR layout

The parser is in aionecpbx, so a new layout is a change there:

1. Take the `last_raw_line` from someone's diagnostics.
2. Add it to aionecpbx's `tests/test_smdr.py` with the result it should give.
3. Adjust aionecpbx's `src/aionecpbx/smdr.py` until it passes, without breaking the others.
4. Release aionecpbx, then raise the pin in `manifest.json` here.

## Layout

| File | |
|---|---|
| aionecpbx `smdr.py` | Turns one SMDR line into a call record. No Home Assistant code, so it is easy to test. |
| aionecpbx `client.py`, `ami.py` | Hold the SMDR and FreePBX connections and reconnect. |
| `__init__.py` | Runs the clients, keeps the call history and fires the events. |
| `sensor.py`, `binary_sensor.py` | The entities. |
| `config_flow.py` | Setup, reconfigure and options. |
| `diagnostics.py` | Diagnostics with numbers masked. |
