# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
shell_command(
    name="manufacture_python_code",
    command='echo print\\(\\"Hello, World!\\"\\) > hello_world.py',
    output_files=["hello_world.py"],
)

shell_command(
    name="manufacture_resource",
    command="echo hi > resource.txt",
    output_files=["resource.txt"],
)


experimental_wrap_as_python_sources(
    name="python_dependency",
    inputs=[":manufacture_python_code"],
)

experimental_wrap_as_resources(
    name="resource_dependency",
    inputs=[":manufacture_resource"],
)

pex_binary(
    name="app",
    dependencies=[":python_dependency", ":resource_dependency"],
    entry_point="testprojects.wrap_as.hello_world",
)
