# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
experimental_shell_command(
    name="manufacture_python_code",
    command='echo print\\(\\"Hello, World!\\"\\) > hello_world.py',  # You need to know the pex filename
    outputs=["hello_world.py"],
)

experimental_export_python(
    name="python_dependency",
    inputs=[":manufacture_python_code"],
)

pex_binary(
    name="app",
    dependencies=[":python_dependency"],
    entry_point="testprojects.magic.hello_world",
)
