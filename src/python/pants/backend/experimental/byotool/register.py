from pants.backend.adhoc import run_system_binary
from pants.backend.adhoc.target_types import SystemBinaryTarget
from pants.backend.byotool import lib
from pants.backend.byotool.lib import ByoLinterTarget


def target_types():
    return [
        SystemBinaryTarget,
        ByoLinterTarget,
    ]


def rules():
    return [
        *run_system_binary.rules(),
        *lib.rules()
    ]
