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
        $ ./pants list //examples/src/java/org/pantsbuild/example/hello/main:main
        examples/src/java/org/pantsbuild/example/hello/main:main

-   The starting double-slash is optional if the target isn't in the build root directory:

        :::bash
        $ ./pants list examples/src/java/org/pantsbuild/example/hello/main:main
        examples/src/java/org/pantsbuild/example/hello/main:main

    It's idiomatic to omit the double-slash when possible.  However it's required when referencing
    targets in the build root, so that the command-line parser can distinguish such targets from
    goal names: `./pants foo bar baz` is ambiguous; `./pants foo //:bar //:baz` is not.
    That said, it's not necessary, or even common, to have targets at the build root, and this
    practice is best avoided anyway.

-   The target name is optional if it is the same as the parent directory name:

        :::bash
        $ ./pants list examples/src/java/org/pantsbuild/example/hello/main
        examples/src/java/org/pantsbuild/example/hello/main:main

    It's idiomatic to omit the repetition of the target name in this case.

-   If the address of the target that owns a certain file is not known, the `--owner-of=` global
    option can be passed to run the goal on the target which own that file.

        ::::bash
        $ ./pants --owner-of=examples/src/java/org/pantsbuild/example/hello/main/HelloMain.java list
        examples/src/java/org/pantsbuild/example/hello/main:main
    
    It's also worth noting that multiple instances of `--owner-of=` are accepted in order to work with multiple
    files and pants will execute the goal on all the targets that own those files. Additionally, `fromfile`
    support is enabled for this option, so passing `--owner-of=@file` (where "file" is a filename
    containing a list of filenames to look up owners for) is supported.

-   Relative paths and trailing forward slashes are ignored on the
    command-line to accommodate tab completion:

        :::bash
        $ ./pants list ./examples/src/java/org/pantsbuild/example/hello/main/
        examples/src/java/org/pantsbuild/example/hello/main:main

    Absolute paths are also allowed on the command-line, to support flexibility in scripting:

        :::bash
        $ pants goal list $REPO_ROOT/src/java/org/pantsbuild/example/hello/main
        src/java/org/pantsbuild/example/hello/main:main

These last two forms are not allowed in target addresses in `BUILD` files.
They are just for command-line convenience.

You can reference another target in the same BUILD file by starting with a
colon ``:targetname`` instead of specifying the whole path:

    :::python
    java_library(name='application', ...)
    java_library(name='mybird',
      dependencies=[':application'],
    )

Note that, apart from this shorthand, addresses in BUILD files are always relative to the buildroot,
not to the referencing BUILD file.

Pants supports two globbing target selectors, as a convenience on the command-line. These forms
are not allowed in BUILD files.

A trailing single colon specifies a glob of targets at the specified location:

    :::bash
    $ ./pants list tests/python/pants_test/:
    tests/python/pants_test:int-test
    tests/python/pants_test:base_test
    tests/python/pants_test:test_infra
    tests/python/pants_test:test_maven_layout

A trailing double colon specifies a recursive glob of targets at the specified location:

    :::bash
    $ ./pants list tests/python/pants_test/::
    tests/python/pants_test:int-test
    tests/python/pants_test:base_test
    tests/python/pants_test:test_infra
    tests/python/pants_test:test_maven_layout
    tests/python/pants_test/base:base
    ...
    tests/python/pants_test/tasks:sort_targets
    tests/python/pants_test/testutils:testutils
