# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.files import Files


class PythonRequirementsFile(Files):
    """A requirements.txt file.

    The python_requirements macro generates python_requirement_library targets and makes them depend
    on a _python_requirements_file() target, so that pantsd knows to invalidate correctly when the
    requirements.txt file changes.  We don't want to use a regular files() target for this, as we
    don't want to consider the requirements.txt a source for the purpose of building pexes (e.g., we
    don't want whitespace changes to requirements.txt to invalidate the sources pex).
    """

    @classmethod
    def alias(cls):
        # The leading underscore in the name is to emphasize that this is used by macros but is
        # not intended to be used in user-authored BUILD files.
        return "_python_requirements_file"
