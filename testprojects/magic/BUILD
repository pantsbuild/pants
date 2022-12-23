# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
experimental_shell_command(
    name="manufacture_python_code",
    command='echo print\\(\\"Hello, World!\\"\\) > hello_world.py',  # You need to know the pex filename
    output_files=["hello_world.py"],
)

experimental_shell_command(
    name="manufacture_resource",
    command="echo hi > resource.txt",  # You need to know the pex filename
    output_files=["resource.txt"],
)


experimental_export_python(
    name="python_dependency",
    inputs=[":manufacture_python_code"],
)

experimental_export_resources(
    name="resource_dependency",
    inputs=[":manufacture_resource"],
)

pex_binary(
    name="app",
    dependencies=[":python_dependency", ":resource_dependency"],
    entry_point="testprojects.magic.hello_world",
)
