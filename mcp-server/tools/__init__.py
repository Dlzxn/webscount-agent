# Importing each module triggers @mcp.tool() decorators,
# which registers the tools in the shared FastMCP instance.
from . import navigate        # noqa: F401
from . import go_back         # noqa: F401
from . import scroll          # noqa: F401
from . import read_page       # noqa: F401
from . import get_full_text   # noqa: F401
from . import get_current_state  # noqa: F401
from . import click           # noqa: F401
from . import type_text       # noqa: F401
from . import select_option   # noqa: F401
from . import press_key       # noqa: F401
from . import handle_dialog   # noqa: F401
from . import list_tabs       # noqa: F401
from . import switch_tab      # noqa: F401
