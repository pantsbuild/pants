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

* Use a code line width of 100 characters.
* Use 2 spaces for indentation.

## String Interpolation

Use f-strings over `.format()` and `%`.

    # Good
    f"Hello {name}!"

    # Bad
    "Hello {}".format(name)
    "Hello %s" % name

## Collection Literals

Use the literals for the various collection types.

    # Good
    a_set = {a}
    a_tuple = (a, b)
    another_tuple = (a,)

    # Bad
    a_set = set([a])
    a_tuple = tuple([a, b])
    another_tuple = tuple([a])
