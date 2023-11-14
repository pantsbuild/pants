# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":kotlin_resources"])
resources(name="kotlin_resources", sources=["*.kt", "*.lock"])

# Dep inference installs its own JDK, we must make sure that works on all platforms.
python_tests(name="tests", timeout=240, tags=["platform_specific_behavior"],)
