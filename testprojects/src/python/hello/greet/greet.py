# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pkgutil

from colors import green


def greet(greetee):
    """Given the name, return a greeting for a person of that name."""
    greeting = pkgutil.get_data(__name__, "greeting.txt").decode().strip()
    return green(f"{greeting}, {greetee}!")
