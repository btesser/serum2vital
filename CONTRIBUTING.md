# Contributing

Thanks for helping make Serum presets play in Vital.

## Ground rules

* Every mapping claim should be measurable. The repository ships two headless
  hosts (`tools/serum_host.py` for Serum via DawDreamer, `tools/vital_host.py`
  for Vital via pedalboard) and an A/B renderer (`tools/ab_render.py`). If you
  change a unit curve or a menu table, re-run `tools/calibrate.py` and paste
  the before/after rows into the pull request.
* Do not guess menu orders or knob curves from preset statistics when the
  plugin can tell you directly: `tools/gen_serum_tables.py` regenerates
  `serum2vital/serum_tables.py` from `tools/serum_display_tables.json`, which
  is a dump of what Serum displays for each parameter.
* New Serum states that are not VST parameters (switches, modes) are located
  with single-change fixture presets; see `docs/FIXTURE_PRESETS_TASK.md` and
  the existing ones under `DebugPresets/`.
* Keep conversion notes honest and prefixed with a fidelity class:
  `approximation:`, `conflict:`, `unsupported:` or `unknown:`.

## Running the tests

```bash
pip install -e .[dev]
python -m pytest
```

Tests that need the Serum preset library or the plugins skip automatically.
Point `SERUM_ROOT` at your Serum data folder (the one holding `Presets/`,
`Tables/` and `Noises/`) to enable the corpus tests, and `SERUM_VST2` /
`VITAL_VST3` at the plugin binaries for the host tools.

## Reporting a bad conversion

Open an issue with the preset (if you are allowed to share it), the
conversion notes from `--report`, and what you hear differently. A/B renders
from `tools/ab_render.py` are the fastest way to make a difference actionable.
