# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.target import Target


class ToolsJar(Target):
    """A private target type injected by the JavacPlugin to represent the JDK's tools.jar.

    The classpath for this target is provided by the ProvideToolsJar task.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(scope="compile", *args, **kwargs)
