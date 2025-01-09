# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_sources(
    overrides={"completion.py": {"dependencies": [":completion-files"]}},
)
resources(name="completion-files", sources=["pants-completion.bash", "pants-completion.zsh"])

python_tests(name="tests", sources=["*_test.py", "!*_integration_test.py"])
python_tests(name="integration", sources=["*_integration_test.py"], timeout=120)
