# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='test_basic_invocation_conversion_rules',
  sources=['test_basic_invocation_conversion_rules.py'],
  dependencies=[
    'contrib/rust/src/python/pants/contrib/rust/utils/basic_invocation:args_rules',
    'contrib/rust/src/python/pants/contrib/rust/utils/basic_invocation:env_rules',
    'contrib/rust/src/python/pants/contrib/rust/utils/basic_invocation:links_rule',
    'contrib/rust/src/python/pants/contrib/rust/utils/basic_invocation:outputs_rule',
  ]
)

python_tests(
  name='test_basic_invocation_conversion_utils',
  sources=['test_basic_invocation_conversion_utils.py'],
  dependencies=[
    'contrib/rust/src/python/pants/contrib/rust/utils:basic_invocation_conversion_utils',
  ]
)

python_tests(
  name='test_custom_build_invocation_conversion_rules',
  sources=['test_custom_build_invocation_conversion_rules.py'],
  dependencies=[
    'contrib/rust/src/python/pants/contrib/rust/utils/custom_build_invocation:args_rules',
    'contrib/rust/src/python/pants/contrib/rust/utils/custom_build_invocation:env_rules',
    'contrib/rust/src/python/pants/contrib/rust/utils/custom_build_invocation:links_rule',
    'contrib/rust/src/python/pants/contrib/rust/utils/custom_build_invocation:outputs_rule',
    'contrib/rust/src/python/pants/contrib/rust/utils/custom_build_invocation:program_rule',
  ]
)

python_tests(
  name='test_custom_build_output_parsing',
  sources=['test_custom_build_output_parsing.py'],
  dependencies=[
    'contrib/rust/src/python/pants/contrib/rust/utils:custom_build_output_parsing',
  ]
)


