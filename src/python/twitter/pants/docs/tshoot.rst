###############
Troubleshooting
###############

Sometimes Pants doesn't do what you hoped. Sometimes it's a problem in your
code, but Pants' error handling is not so useful. (Please report these when
you see them. We want Pants' error messages to be useful.) Sometimes Pants
just plain doesn't work. (Please report these, too.) The following workarounds
can get you up and running again.

.. _verbosity:

*****************
Maximum Verbosity
*****************

To run a Pants command so that it outputs much much more information to stdout,
you can set some environment variables and pass the ``-ldebug`` flag (along
with the parameters you meant to pass)::

    PEX_VERBOSE=1 PANTS_VERBOSE=1 PYTHON_VERBOSE=1 ./pants -ldebug ...

This can be especially useful if you're trying to figure out what Pants
was "looking at" when it crashed.

.. _washpants:

*********************
Scrub the Environment
*********************

If you suspect that Pants has cached some corrupt data somewhere, but don't
want to track down exactly what, you can reset your state::

    $ build-support/python/clean.sh # clean cached files
    $ ./pants goal ng-killall --ng-killall-everywhere # stop background procs


