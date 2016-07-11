IDE Support
===========

Pants Plugin for IntelliJ IDEA
------------------------------

The easiest way to use Pants with IntelliJ is to install the Pants plugin.
For details, see the
[IntelliJ-pants-plugin README](https://github.com/pantsbuild/intellij-pants-plugin/blob/master/README.md).


Ensime Project Generator
------------------------

Ensime is the ENhanced Scala Interaction Mode for GNU Emacs, providing code
navigation, type inspection and more. To install ensime follow the instructions at
<https://github.com/ensime/ensime-server>

Pants can generate an ensime project file:

    :::bash
    $ ./pants ensime src/java/com/archie/path/to:target

This will generate a project for the code in the specified target and all its transitive dependencies.
