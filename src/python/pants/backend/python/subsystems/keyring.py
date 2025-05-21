from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript


class KeyringSubsystem(PythonToolBase):
    options_scope = "keyring"
    name = "Keyring"
    help_short = "The keyring utility used to authenticate to private PyPI repositories."

    default_version = "keyring==23.4.1"
    default_main = ConsoleScript("keyring")

    default_requirements = ["keyring"]
    default_interpreter_constraints = ["CPython>=3.6,<4"]

    register_interpreter_constraints = True
