# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.target import StringSequenceField, Targets
from pants.util.strutil import softwrap


class StevedoreNamespace(str):
    """Syntactic sugar to tag a namespace in entry_points as a stevedore namespace.

    For example:
        python_distribution(
            ...
            entry_points={
                stevedore_namespace("a.b.c"): {
                    "plugin_name": "some.entry:point",
                },
            },
        )
    """


# This is a lot like a SpecialCasedDependencies field, but it doesn't list targets directly.
class StevedoreNamespacesField(StringSequenceField):
    alias = "stevedore_namespaces"
    help = softwrap(
        """
        List the stevedore namespaces required by this target.

        All stevedore_extension targets with these namespaces will be added as
        dependencies so that they are available on PYTHONPATH during tests.
        The stevedore namespace format (my.stevedore.extension) is similar
        to a python namespace.
        """
    )


class AllStevedoreExtensionTargets(Targets):
    pass


@dataclass(frozen=True)
class StevedoreNamespacesProviderTargetsRequest:
    stevedore_namespaces: StevedoreNamespacesField


class StevedoreExtensionTargets(Targets):
    pass
