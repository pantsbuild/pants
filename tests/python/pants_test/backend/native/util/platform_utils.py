# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.platform import Platform
from pants.util.osutil import all_normalized_os_names


def platform_specific(normalized_os_name):
    if normalized_os_name not in all_normalized_os_names():
        raise ValueError(f"unrecognized platform: {normalized_os_name}")

    def decorator(test_fn):
        def wrapper(self, *args, **kwargs):
            if Platform.current == Platform(normalized_os_name):
                test_fn(self, *args, **kwargs)

        return wrapper

    return decorator
