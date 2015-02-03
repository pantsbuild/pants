Troubleshooting
===============

Sometimes Pants doesn't do what you hoped.
Pants has good error messages for common errors, but
some messages are not so useful.
(Please report these when you see them.
We want Pants' error messages to be useful.)
Sometimes Pants just plain doesn't work. (Please report these, too.) The
following workarounds can get you up and running again.

<a pantsmark="tshoot_verbosity"> </a>

Maximum Verbosity
-----------------

To run a Pants command so that it outputs much much more information to
stdout, you can set some environment variables and pass the `-ldebug`
flag (along with the parameters you meant to pass):

    :::bash
    $ PEX_VERBOSE=1 PANTS_VERBOSE=1 PYTHON_VERBOSE=1 ./pants -ldebug ...

This can be especially useful if you're trying to figure out what Pants
was "looking at" when it crashed.

<a pantsmark="washpants"> </a>

Scrub the Environment
---------------------

If you suspect that Pants has cached some corrupt data somewhere, but
don't want to track down exactly what, you can reset your state:

-   **Clean many cached files:** `./build-support/python/clean.sh`
-   **Clean more cached files:** If your source tree lives under source
    control, use your source control tool to clean up more files. For
    example with `git`, you might do something like:

        :::bash
        $ git status  # look for untracked files
        $ git add path/to/file1 path/to/file2  # preserve untracked files you don't want deleted
        $ git clean -fdx  # delete all untracked files

-   **Stop background processes:**

        :::bash
        $ ./pants ng-killall --everywhere

Nailgun 10 seconds
------------------

If Pants fails with a stack trace that ends with something like

    :::bash
    File "pants/tasks/nailgun_task.py", line 255, in _spawn_nailgun_server
    File "pants/tasks/nailgun_task.py", line 226, in _await_nailgun_server
    pants.java.nailgun_client.NailgunError: Failed to read ng output after 10 seconds...

The exception might show some command args.

Pants uses a program called nailgun to run some JVM jobs. Pants runs
nailgun as a server in the background and then sends requests to it. If
nailgun runs into problems, it might not respond.

To debug this, look in `.pants.d/ng/*/*`: these files should be named
`stdout` and `stderr`.

One typical cause behind this symptom: if you removed your machine's Ivy
cache, Pants may try to use symbolic links to files that have gone away.
To recover from this, <a pantsref="washpants">scrub the environment</a>.

Questions, Issues, Bug Reports
------------------------------

See [[How to Ask|pants('src/python/pants/docs:howto_ask')]]
