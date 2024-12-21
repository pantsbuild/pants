# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.engine.rules import collect_rules
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class K8sSubsystem(Subsystem):
    name = "k8s"
    options_scope = "k8s"
    help = "Kubernetes options"

    available_contexts = StrListOption(
        default=[],
        help=softwrap(
            """
            List of available contexts for `kubectl` command. `k8s_bundle`
            context will be validated against this list.

            You have to explicitly provide the list, because it will be shared
            with people using the pants repo. We can't parse the KUBE_CONFIG
            env var because different people might have different private
            clusters, e.g. minikube or kind, which means pants validation will
            give different results.
            """
        ),
    )


def rules():
    return collect_rules()
