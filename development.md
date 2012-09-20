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
repositories. Publishing requires pgp signing, but this can be turned off.

Publish to `~/.ivy2/local` (without signing):

    sbt> set skip in com.jsuereth.pgp.sbtplugin.PgpKeys.pgpSigner := true
    sbt> publish-local

Publish to `~/.m2/repository` (without signing):

    sbt> set skip in com.jsuereth.pgp.sbtplugin.PgpKeys.pgpSigner := true
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
