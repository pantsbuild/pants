Welcome to the Pants build system.
==================================

Pants is a build system for software projects in a variety of languages.
It works particularly well for a source code repository that contains
many distinct projects.

Getting started using Pants
---------------------------

Tutorials and basic concepts. How to use Pants to build things. How to
configure build-able things in BUILD files.
<!-- TODO(lahosken) proper link for some things below -->

+ [[Pants Conceptual Overview|pants('src/docs:first_concepts')]]
+ [[First Tutorial|pants('src/docs:first_tutorial')]]
+ <a href="target_addresses.html">Target Addresses</a>
+ [[JVM Projects|pants('examples/src/java/com/pants/examples:readme')]]
+ [[Python Projects|pants('examples/src/python/example:readme')]]
+ <a href="page.html">README Files and Markdown</a>
+ [[Pants Conceptual Overview|pants('src/docs:build_files')]]
+ <a href="invoking.html">Invoking Pants Build</a>
+ <a href="tshoot.html">Troubleshooting</a>

Troubleshooting
---------------

+   Something that usually works just failed? See
    <!-- TODO(lahosken) proper link -->
    <a href="tshoot.html">Troubleshooting</a>.
+   Publishing can fail in more ways. See
    [[Publishing Artifacts|pants('src/docs:publish')]].

Pants Patterns
--------------

Common Pants build idioms.

+ [[Third-Party Dependencies|pants('src/docs:3rdparty')]]
+ [[Thrift|pants('examples/src/thrift/com/pants/examples:readme')]]
+ [[Publishing Artifacts|pants('src/docs:publish')]]

Using Pants With...
-------------------

+ <a href="with_emacs.html">Emacs and Ensime</a>
+ <a href="with_intellij.html">IntelliJ IDEA</a>

News
----

+ [[2014-09-16 Announcement|pants('src/docs:announce_201409')]]
  "Hello Pants Build"

Advanced Documentation
----------------------

+ <a href="setup_repo.html">Set up your Source Tree for Pants</a>
+ [[Installing Pants|pants('src/docs:install')]]

Pants Reference Documentation
-----------------------------

+ <a href="build_dictionary.html">BUILD Dictionary</a>
+ <a href="goals_reference.html">Goals Reference</a>

Contributing to Pants
---------------------

How to develop Pants itself and contribute your changes.

+ [[Pants Developer Center|pants('src/python/pants/docs:readme')]]
