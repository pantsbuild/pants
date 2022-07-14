# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


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
