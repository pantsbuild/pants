# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.optionable import Optionable


# TODO: Unite Optionable and Subsytem, since we no longer have any othe subtypes of
#  Optionable, and Subsystem is now sufficiently trivial.
class Subsystem(Optionable):
    """A separable piece of functionality that may be reused across multiple tasks or other code.

    Subsystems encapsulate the configuration and initialization of things like JVMs,
    Python interpreters, SCMs and so on.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.

    :API: public
    """
