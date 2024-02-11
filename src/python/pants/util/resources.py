# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import importlib.resources
from itertools import chain


def read_resource(package_or_module: str, resource: str) -> bytes:
    """Reads a resource file from within the Pants package itself.

    This helper function is designed for compatibility with `pkgutil.get_data()` wherever possible,
    but also allows compatibility with PEP302 pluggable importers such as included with PyOxidizer.
    """

    a = importlib.import_module(package_or_module)
    package_: str = a.__package__  # type: ignore[assignment]
    resource_parts = resource.split("/")

    if len(resource_parts) == 1:
        package = package_
    else:
        package = ".".join(chain((package_,), resource_parts[:-1]))
        resource = resource_parts[-1]

    return importlib.resources.files(package).joinpath(resource).read_bytes()


def read_sibling_resource(sibling_name: str, resource: str) -> bytes:
    """A convenience function for reading a resource that is a sibling of the calling module.

    The caller should pass __name__ as the name arg, and the relpath to the resource as the resource
    arg.
    """
    return read_resource(sibling_name.rpartition(".")[0], resource)
