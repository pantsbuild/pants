from pants.option.option_types import BoolOption
from pants.util.strutil import softwrap

from pants.backend.docker.subsystems.docker_options import DockerOptions

class ExperimentalPodmanOptions:
    experimental_enable_podman = BoolOption(
        default=True,
        help=softwrap(
            """
            Allow support for podman when available.
            """
        ),
    )


def rules():
    return [
        DockerOptions.register_plugin_options(ExperimentalPodmanOptions),
    ]