# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
	dependencies=[':java_src']
)
python_tests(name="tests", timeout=240)

resources(
  name='java_src',
  sources=['*.java'],
)
