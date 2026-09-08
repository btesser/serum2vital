# Third-party material in tools/

* `synth_parameters.cpp` is an unmodified copy of Vital's parameter table
  (https://github.com/mtytel/vital, GPL-3.0). It is kept so that
  `gen_vital_defaults.py` can regenerate `serum2vital/vital_defaults.py`
  offline. This repository is distributed under the GPL-3.0 as a whole.
* `serum_display_tables.json` contains the display strings and knob read-outs
  captured from the Serum plugin on the author's machine; it is a description
  of the plugin's user interface, not any part of its code.
* The hosts in `serum_host.py` and `vital_host.py` need the plugins installed
  locally; nothing from either plugin is bundled here.
