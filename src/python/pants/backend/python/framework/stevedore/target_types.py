# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.target_types import PythonDistribution
from pants.engine.target import StringSequenceField, Targets
from pants.util.strutil import help_text


class StevedoreNamespace(str):
    """Tag a namespace in entry_points as a stevedore namespace.

    This is required for the entry_point to be visible to dep inference
    based on the `stevedore_namespaces` field.

    For example:
    ```python
    python_distribution(
        ...
        entry_points={
            stevedore_namespace("a.b.c"): {
                "plugin_name": "some.entry:point",
            },
        },
    )
    ```
    """

    alias = "stevedore_namespace"


# This is a lot like a SpecialCasedDependencies field, but it doesn't list targets directly.
class StevedoreNamespacesField(StringSequenceField):
    alias = "stevedore_namespaces"
    help = help_text(
        f"""
        List the stevedore namespaces required by this target.

        Code for all `entry_points` on `{PythonDistribution.alias}` targets with
        these namespaces will be added as dependencies so that they are
        available on PYTHONPATH during tests. Note that this is only a subset
        of the `{PythonDistribution.alias}`s dependencies, so the `entry_points`
        only need to be defined on one `{PythonDistribution.alias}` even if the
        test only needs some of the `entry_points` namespaces on it.

        Plus, an `entry_points.txt` file will be generated in the sandbox so that
        each of the `{PythonDistribution.alias}`s appear to be "installed". The
        `entry_points.txt` file will only include the namespaces requested on this
        field. Without this, stevedore would not be able to look up plugins in
        the setuptools `entry_points` metadata.

        NOTE: Each `{PythonDistribution.alias}` must opt-in to being included in
        this repo-wide inference by tagging the namespaces with
        `{StevedoreNamespace.alias}("my.stevedore.extension")`.

        The stevedore namespace format (`my.stevedore.extension`) is similar
        to a Python namespace.
        """
    )


class AllStevedoreExtensionTargets(Targets):
    pass


@dataclass(frozen=True)
class StevedoreNamespacesProviderTargetsRequest:
    stevedore_namespaces: StevedoreNamespacesField


class StevedoreExtensionTargets(Targets):
    pass
