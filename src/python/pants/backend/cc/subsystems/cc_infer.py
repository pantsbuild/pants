# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import BoolOption, StrListOption
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
        help="Infer a target's dependencies by trying to include relative to source roots.",
    )

    include_dir_names = StrListOption(
        default=["include", "includes", "inc"],
        help=softwrap(
            """
            Infer a target's dependencies by trying to search for header files relative to SOURCE_ROOT + INCLUDE_DIR_NAME.

            The inferred header files take part in compilation, and the inferred relative directory is added to compilation
            arguments prefixed by the '-I' flag.
            """
        ),
    )
