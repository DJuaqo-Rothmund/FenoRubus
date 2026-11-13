"""
ui/screens.py
=============
Pantallas y widgets de la app, ahora divididos por pantalla (ui/common.py, ui/home.py,
ui/sampling.py, ui/observation.py, …). Este módulo los reúne para que `from ui.screens
import X` siga funcionando. El diseño está en ui/kv/*.kv.
"""
from ui.common import *  # noqa: F401,F403
from ui.home import *  # noqa: F401,F403
from ui.sectors_ui import *  # noqa: F401,F403
from ui.workspaces_ui import *  # noqa: F401,F403
from ui.sampling import *  # noqa: F401,F403
from ui.varieties_ui import *  # noqa: F401,F403
from ui.observation import *  # noqa: F401,F403
from ui.preview import *  # noqa: F401,F403
from ui.reports_ui import *  # noqa: F401,F403
from ui.settings_ui import *  # noqa: F401,F403
from ui.ailab import *  # noqa: F401,F403
from ui.measures_ui import *  # noqa: F401,F403
