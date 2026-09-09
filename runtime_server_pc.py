from __future__ import annotations

"""PC-only launcher.

Preserves the repository's current Render emergency NHPLUG block, but restores
NHPLUG only inside the dedicated PC process before starting runtime_server_v34.
"""

import importlib
import os
import runpy

os.environ["NAMUH_PC_SERVER"] = "1"

# sitecustomize has already run by the time this launcher starts.  Keep all of
# its UI/runtime fixes, but stop its later uvicorn wrapper from re-applying the
# emergency NHPLUG block in this PC-only process.
import sitecustomize

if hasattr(sitecustomize, "_namuh_emergency_disable_nhplug"):
    sitecustomize._namuh_emergency_disable_nhplug = lambda: None

# Restore the package functions that the emergency block replaced.  This is
# process-local; it does not modify Render/main or credential files.
import nhplug.auth as _nh_auth
import nhplug.instruments as _nh_instruments
import nhplug.realtime as _nh_realtime
import nhplug as _nhplug

importlib.reload(_nh_auth)
importlib.reload(_nh_instruments)
importlib.reload(_nh_realtime)
importlib.reload(_nhplug)

# Run the existing v34 runtime unchanged so all verified strategy/UI patches
# remain the same.
runpy.run_module("runtime_server_v34", run_name="__main__")
