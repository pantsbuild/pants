Target Addresses
================

Every Pants target has an _address_, which is a combination of the BUILD file path and target name.
Addresses are used in two main contexts:

+ To reference targets as dependencies in BUILD files,
+ From the command-line, to specify what targets to act on.

<a pantsmark="addresses_synonyms"> </a>

The following target addresses all specify the same single target.

-   The fully qualified target address is `//` plus the BUILD file's directory path plus target name:

        :::bash
        $ ./pants list //src/python/myproject/example/hello/main:main
        src/python/myproject/example/hello/main:main

-   The starting double-slash is optional if the target isn't in the build root directory:

        :::bash
        $ ./pants list src/python/myproject/example/hello/main:main
        src/python/myproject/example/hello/main:main

    It's idiomatic to omit the double-slash when possible.  However it's required when referencing
    targets in the build root, so that the command-line parser can distinguish such targets from
    goal names: `./pants foo bar baz` is ambiguous; `./pants foo //:bar //:baz` is not.
    That said, it's not necessary, or even common, to have targets at the build root, and this
    practice is best avoided anyway.

-   The target name is optional if it is the same as the parent directory name:

        :::bash
        $ ./pants list src/python/myproject/example/hello/main
        src/python/myproject/example/hello/main:main

    It's idiomatic to omit the repetition of the target name in this case.

-   Relative paths and trailing forward slashes are ignored on the
    command-line to accommodate tab completion:

        :::bash
        $ ./pants list ./src/python/myproject/example/hello/
        src/python/myproject/example/hello:app

    Absolute paths are also allowed on the command-line, to support flexibility in scripting:

        :::bash
        $ pants list $REPO_ROOT/src/python/myproject/example/hello
        src/python/myproject/example/hello:app

These last two forms are not allowed in target addresses in `BUILD` files.
They are just for command-line convenience.

You can reference another target in the same BUILD file by starting with a
colon ``:targetname`` instead of specifying the whole path:

    :::python
    java_library(
      name='application',
      ...,
     )
     
    java_library(
      name='mybird',
      dependencies=[
        ':application',
      ],
    )

Note that, apart from this shorthand, addresses in BUILD files are always relative to the buildroot,
not to the referencing BUILD file.

Pants supports two globbing target selectors, as a convenience on the command-line. These forms
are not allowed in BUILD files.

A trailing single colon specifies a glob of targets at the specified location:

    :::bash
    $ ./pants list src/python/pants/util:
    src/python/pants/util:argutil
    src/python/pants/util:collections
    src/python/pants/util:contextutil
    src/python/pants/util:desktop
    ...
   

A trailing double colon specifies a recursive glob of targets at the specified location:

    :::bash
    $ ./pants list src/python/pants/backend/project_info::
    src/python/pants/backend/project_info/tasks:all
    src/python/pants/backend/project_info/tasks:dependencies
    src/python/pants/backend/project_info/tasks:depmap
    ...
    src/python/pants/backend/project_info/rules:rules
    src/python/pants/backend/project_info/rules:tests
    src/python/pants/backend/project_info:plugin

Alternative: File args
======================

Instead of specifying the address, you may instead simply specify the file you want Pants to operate on. Pants will find all owner(s) and operate over those owning targets.

    :::bash
    $ ./pants list src/python/myproject/example.py
    src/python/myproject:lib

You may pass multiple files and even use globs, with the same syntax as the `sources` field in BUILD files (see [[Use globs to group files|pants('src/docs/common_tasks:globs')]]):

    :::bash
    # This will format every `.py` file under `src/python/myproject`, except for `ignore.py`
    $ ./pants fmt 'src/python/myproject/**/*.py' '!src/python/myproject/ignore.py'

You may use the `--spec-file` option to pass a text file with a list of all the files you'd like Pants to operate on (with a newline separating each file):

    :::bash
    $ echo 'src/python/myproject/f1.py
      src/python/myproject/f2.py
      src/python/myproject/example/*.py' > to_be_formatted.txt
    $ ./pants --spec-file=to_be_formatted.txt fmt
