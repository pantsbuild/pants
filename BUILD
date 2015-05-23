# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Pants source code
source_root('src/java', page, java_library, jvm_binary)
source_root('src/python', page, python_binary, python_library, resources)
source_root('src/resources', page, resources)
source_root('src/scala', page, scala_library, jvm_binary)

# Pants test code
source_root('tests/java', page, java_library, junit_tests, jvm_binary)
source_root('tests/python', page, python_library, python_tests, python_test_suite, python_binary,
                            resources)
source_root('tests/resources', page, resources)

# Pants own plugins for this repo's exclusive use
source_root('pants-plugins/src/python', page, python_binary, python_library, resources)
source_root('pants-plugins/tests/python', page, python_library, python_tests, python_test_suite,
                                          python_binary, resources)

page(name="readme", source="README.md")
