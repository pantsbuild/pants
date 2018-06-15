# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
    name = "fasthello",
    sources = [
        "c_greet.c",
        "cpp_greet.cpp",
        "hello_package/__init__.py",
        "hello_package/hello.py",
        "setup.py",
    ],
)

python_binary(
    name = "main_with_no_conflict",
    source = "main.py",
    platforms = ["current"],
    dependencies = [
        ":fasthello",
    ],
)

python_binary(
    name = "main_with_conflicting_dep",
    source = "main.py",
    platforms = ["current"],
    dependencies = [
        ":fasthello",
        ":pycountry",
    ],
)

python_requirement_library(
    name = "pycountry",
    requirements = [
        python_requirement("pycountry==17.9.23"),
    ],
)

python_binary(
    name = "main_with_no_pycountry",
    source = "main.py",
)
