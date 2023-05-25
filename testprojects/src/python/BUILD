# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(name="build_file_imports_function_directory", sources=["build_file_imports_function/**/*"])

files(name="build_file_imports_module_directory", sources=["build_file_imports_module/**/*"])

files(name="coordinated_runs_directory", sources=["coordinated_runs/**/*"])

files(name="hello_directory", sources=["hello/**/*"])

files(name="mypyc_fib_directory", sources=["mypyc_fib/**/*"])

files(name="native_directory", sources=["native/**/*"])

files(name="no_build_file_directory", sources=["no_build_file/**/*"])

files(name="print_env_directory", sources=["print_env/**/*"])

files(name="sources_directory", sources=["sources/**/*"])

run_shell_command(
    name="cmd",
    command='{ find {chroot} -type f; echo "in: $CHROOT"; } | tee output.log',
    execution_dependencies=[":hello_directory"],
)
