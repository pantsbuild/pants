# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class CCInferSubsystem(Subsystem):
    options_scope = "cc-infer"
    help = "Options controlling which dependencies will be inferred for CC targets."

    includes = BoolOption(
        default=True,
        help="Infer a target's dependencies by parsing #include statements from sources.",
    )

    # TODO: This option may move to a proper `cc` subsystem once compilation is implemented. It may also
    # change depending on how we want to model in-repo includes.
    include_from_source_roots = BoolOption(
        default=True,
        help=softwrap(
            """
            Infer a target's dependencies by trying to include relative to source roots.

            An example where this may be useful is if you have a a file at `root/include/mylib/foo.h`
            which may be referenced via `#include "mylib/foo.h"`. This option will allow you to
            correctly infer dependencies if you have a source root at `root/{include}` and searching for
            `mylib/foo.h` relative to the that source root.

            The inferred files take part in compilation, and the source root is added to the compilation
            include search path (https://clang.llvm.org/docs/ClangCommandLineReference.html#include-path-management)
            with command line arguments prefixed by the '-I' flag.
            """,
        ),
    )
