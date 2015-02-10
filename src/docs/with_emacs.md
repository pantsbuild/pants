Emacs With Pants
================

Emacs doesn't have much special support for Pants; but if you
also use Scala, you might like:

Ensime with Pants
-----------------

Ensime is ENhanced Scala Interaction Mode for GNU Emacs providing code
navigation, type inspection, a lot of things that modern IDE should
support. To install ensime please follow the instructions at
<https://github.com/ensime/ensime-server>

To generate ensime project file for `src/java/com/archie/path/to:target`
one just need to run this command:

    :::bash
    $ ./pants ensime src/java/com/archie/path/to:target

