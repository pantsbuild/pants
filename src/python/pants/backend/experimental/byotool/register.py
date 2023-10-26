from pants.backend.byotool import lib
from pants.backend.byotool.lib import ByoTool


def target_types():
    return []


def rules():
    return [
        # *ByoTool.rules(),
        *lib.rules()
    ]
