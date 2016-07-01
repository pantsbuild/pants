Pants Style Guide
=================

The Pants project has accumulated a number of conventions around organizing code within the project.
This document tries to cover some of the common style issues that new contributors run into in their
first contributions to the project.

A number of style checks are already automated. Some of these are covered by the pre-commit script
([[setup instructions|pants('src/docs:howto_contribute')#getting-pants-source-code]]).
Others are run as when tests are run.

Beyond that, we've got a number of guidelines that haven't been automated.

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

## Collection Literals

Where possible, use the literals for the various collection types.

### Sets

    a_set = {a}
    # Instead of
    a_set = set([a])

### Tuples

    a_tuple = (a, b)
    another_tuple = (a,)
    # Instead of
    a_tuple = tuple([a, b])
    another_tuple = tuple([a])
