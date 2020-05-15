# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':bad_requirements_directory',
    ':build_file_imports_function_directory',
    ':build_file_imports_module_directory',
    ':coordinated_runs_directory',
    ':interpreter_selection_directory',
    ':nested_runs_directory',
    ':no_build_file_directory',
    ':plugins_directory',
    ':print_env_directory',
    ':python_distribution_directory',
    ':python_targets_directory',
    ':sources_directory',
    ':unicode_directory',
  ],
)

files(
  name = 'bad_requirements_directory',
  sources = ['bad_requirements/**/*'],
)

files(
  name = 'build_file_imports_function_directory',
  sources = ['build_file_imports_function/**/*'],
)

files(
  name = 'build_file_imports_module_directory',
  sources = ['build_file_imports_module/**/*'],
)

files(
  name = 'coordinated_runs_directory',
  sources = ['coordinated_runs/**/*'],
)

files(
  name = 'interpreter_selection_directory',
  sources = ['interpreter_selection/**/*'],
)

files(
  name = 'nested_runs_directory',
  sources = ['nested_runs/**/*'],
)

files(
  name = 'no_build_file_directory',
  sources = ['no_build_file/**/*'],
)

files(
  name = 'plugins_directory',
  sources = ['plugins/**/*'],
)

files(
  name = 'print_env_directory',
  sources = ['print_env/**/*'],
)

files(
  name = 'python_distribution_directory',
  sources = ['python_distribution/**/*'],
  dependencies = [
    'testprojects/3rdparty:python_directory',
  ],
)


files(
  name = 'python_targets_directory',
  sources = ['python_targets/**/*'],
)

files(
  name = 'sources_directory',
  sources = ['sources/**/*'],
)

files(
  name = 'unicode_directory',
  sources = ['unicode/**/*'],
)
