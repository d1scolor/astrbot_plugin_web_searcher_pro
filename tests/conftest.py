import os
import sys
import types

PLUGIN_ROOT = os.path.dirname(os.path.dirname(__file__))
PLUGIN_PARENT = os.path.dirname(PLUGIN_ROOT)
for entry in (PLUGIN_PARENT,):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# Support the plugin's actual AstrBot import namespace in a standalone checkout.
for name, paths in (("data", []), ("data.plugins", [PLUGIN_PARENT])):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = paths
        sys.modules[name] = module
