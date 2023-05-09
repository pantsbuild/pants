# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirements(
    module_mapping={
        "strawberry-graphql": ["strawberry"],
        "beautifulsoup4": ["bs4"],
        "python-gnupg": ["gnupg"],
    },
    overrides={
        "humbug": {"dependencies": ["#setuptools", "#urllib3"]},
    },
)

# Useful when using IntelliJ/PyCharm remote debugging. Importing `pydevd_pycharm` at
# the breakpoint will cause dep inference to add this dep on the remote debugger client.
python_requirement(name="pydevd-pycharm", requirements=["pydevd-pycharm==203.5419.8"])
