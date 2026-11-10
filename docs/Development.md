# Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt ruff
pytest
ruff check . && ruff format --check .
```

The tests include a fake phone system: a TCP server that sends SMDR lines, splits them across packets and drops the connection, so the whole integration is tested end to end.

## Adding a new SMDR layout

1. Take the `last_raw_line` from someone's diagnostics.
2. Add it to `tests/test_smdr.py` with the result it should give.
3. Adjust `custom_components/nec_pbx/smdr.py` until it passes, without breaking the others.

## Layout

| File | |
|---|---|
| `smdr.py` | Turns one SMDR line into a call record. No Home Assistant code, so it is easy to test. |
| `client.py` | Holds the TCP connection and reconnects. |
| `__init__.py` | Runs the client, keeps the call history and fires the events. |
| `sensor.py`, `binary_sensor.py` | The entities. |
| `config_flow.py` | Setup, reconfigure and options. |
| `diagnostics.py` | Diagnostics with numbers masked. |
