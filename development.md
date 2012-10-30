Development Notes
=================

Information for developers.


Build
-----

To build everything:

    sbt> dist/create

This will create a runnable zinc command at `dist/target/zinc-<VERSION>/bin/zinc`
that can be used for command-line based testing.


Publish Locally
---------------

The zinc libraries can also be published locally to the local ivy or maven
repositories.

Publish to `~/.ivy2/local`:

    sbt> publish-local

Publish to `~/.m2/repository`:

    sbt> set Publish.publishLocally := true
    sbt> publish


Test
----

The build also has its own simple testing framework. Tests are in `src/scriptit`.
To run all the tests:

    sbt> scriptit

You can run individual tests. For example:

    sbt> scriptit analysis/rebase

Or groups of tests:

    sbt> scriptit analysis/*

Tab completion available.

The default output from tests is minimal. You can show the full output of the
previous test run with:

    sbt> last scriptit

Failures in tests will automatically show the full debug output.


Local sbt
---------

To build zinc against a locally published version of sbt, the sbt jars need to
be republished for maven under `com.typesafe.sbt`.

First publish [sbt] itself locally with:

    sbt> publish-local

Use the [sbt-republish] project to publish sbt to the local maven repository
with:

    sbt> set every publishLocally := true
    sbt> publish

In the zinc project use only the local version of sbt with this setting:

    sbt> set resolveSbtLocally := true

[sbt]: https://github.com/harrah/xsbt
[sbt-republish]: https://github.com/typesafehub/sbt-republish
