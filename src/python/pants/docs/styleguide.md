Pants Style Guide
=================

The Pants project has accumulated a number of conventions around organizing code within the project.
This document tries to cover some of the common style issues that new contributors run into in their
first contributions to the project.


## File Copyright Headers

Any new file must have a copyright header with the current year.

    # coding=utf-8
    # Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
    # Licensed under the Apache License, Version 2.0 (see LICENSE).


## Comments

Comments must have a space after the starting `#`. All comments must be formed with complete
sentences including a period.

Good

    # This is a good comment.

Bad

    #Not This


## Indentation, Line lengths

* Pants uses a code line width of 100 characters.
* Pants code uses 2 spaces for indentation.

## String Interpolation and formatting

* Prefer `.format` for formatting strings over using `%`.


## Python Linting

Our CI fails on linting problems in Python files that make up Pants. Currently, it will check
import sorting as well as whitespace between class and function declarations.

Most whitespace linting failures are exposed when python tests are run.

Import sorting failures or trailing newline failures can be fixed by the following command.

    $ build-support/bin/isort.sh -f