# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":analyze_package_sources", ":generate_testmain_sources"])
python_tests(name="tests", timeout=120)

resource(name="generate_testmain_sources", source="generate_testmain.go")
resource(name="analyze_package_sources", source="analyze_package.go")
