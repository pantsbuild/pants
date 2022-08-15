# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import importlib
from itertools import chain

import importlib_resources as resources


def read_resource(package_or_module: str, resource: str) -> bytes:
    """Reads a resource file from within the Pants package itself.

    This helper function is designed for compatibility with `pkgutil.get_data()` wherever possible,
    but also allows compability with PEP302 pluggable importers such as included with PyOxidizer.
    """

    a = importlib.import_module(package_or_module)
    package_: str = a.__package__  # type: ignore[assignment]
    resource_parts = resource.split("/")

    if len(resource_parts) == 1:
        package = package_
    else:
        package = ".".join(chain((package_,), resource_parts[:-1]))
        resource = resource_parts[-1]

    return resources.read_binary(package, resource)
