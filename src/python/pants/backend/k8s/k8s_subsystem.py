import logging

from pants.engine.rules import collect_rules
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class K8sSubsystem(Subsystem):
    name = "k8s"
    options_scope = "k8s"
    help = "Kubernetes options"

    # TODO: use https://github.com/pantsbuild/pants/pull/20358
    publish_dependencies = BoolOption(
        default=True,
        help="Deploy dependencies in `experimental-deploy` goal.",
    )


def rules():
    return collect_rules()
