If you're setting up the Pants build tool to work in your repo, you probably
want to configure Pants' behavior.
(Once it's set up, most folks should be able to use the
[[normal Pants workflow|pants('src/python/twitter/pants:readme')]] and not
worry about these things.)

[TOC]

## Configure Code Layout with `source_root`

Maybe someday all the world's programmers will agree on the one true directory
structure for code repositories. Until then, you'll want some `source_root`
rules in your repo's top-level `BUILD` file to specify which directories hold
your repo's code. A typical programming language has a notion of _base paths_
for imports; you configure pants to tell it those base paths.

If your top-level `BUILD` file is `foo/BUILD` and your main Java code is in
`foo/src/java/com/foo/` and your Java tests are in `foo/src/javatest/com/foo/`,
then your top-level `BUILD` file might look like

    # foo/BUILD
    source_root('src/java')
    source_root('src/javatest')

Pants can optionally enforce that only allowed target types are in each source root:

    # foo/BUILD
    source_root('src/java', annotation_processor, doc, jvm_binary, java_library, page)
    source_root('src/javatest', doc, java_library, java_tests, page)

If your source tree is laid out for Maven, there's a shortcut function
`maven_layout` that configures source roots for Maven's expected
source code tree structure.

## `BUILD.*` for environment-specific config

When we said `BUILD` files were named `BUILD`, we really meant `BUILD` or
`BUILD.`_`something`_. If you have some rules that make sense for folks in
one environment but not others, you might put them into a separate
BUILD file named `BUILD.`_`something`_.

### Top-level `BUILD.*` for repo-global config

When you invoke `./pants goal` _`something`_ `src/foo:foo` it processes
the code in `src/foo/BUILD` and the code in `./BUILD` _and_ `./BUILD.*`. If you
distribute code to different organizations, and want different configuration
for them, you might put the relevant config code in `./BUILD.something`.
You can give that file to some people and not-give it to others.

For example, you might work at the Foo Corporation, which maintains a fleet
of machines to run big test jobs. You might define a new `goal` type to
express sending a test job to the fleet:

    goal(name='test_on_fleet',
         action=SendTestToFleet,
         dependencies=[]).install().with_description('Send test to Foo fleet')

If the testing fleet is only available on Foo's internal network and you
open-source this repo, you don't want to expose `test_on_fleet` to the world.
You'd just get complaints about `Host testfleet.intranet.foo.com not found`
errors.

You might put this code in a `./BUILD.foo` in the top-level directory of the
internal version of the repo; then hold back this file when mirroring for
the public repository. Thus, the foo-internal-only rules will be available
inside Foo, but not to the world.

### BUILD.* in the source tree for special targets

If you distribute code to different organizations, you might want to expose some
targets to one organization but not to another. You can do this by defining
those targets in a `BUILD.*` file. You can give that file to some people and
not-give it to others. This code will be processed by people invoking pants
on this directory only if they have the file.

For example, you might work at the Foo Corporation, which maintains a fleet
of machines to run big test jobs. You might define a humungous test job
as a convenient way to send many many tests to the fleet:

    # src/javatest/com/foo/BUILD.foo
    
    # many-many test: Run this on the fleet, not your workstation
    # (unless you want to wait a few hours for results)
    junit_tests(name='many-many',
    dependencies = [
      'bar/BUILD:all',
      'baz/BUILD:all',
      'garply/BUILD:all',
    ],)

If you don't want to make this test definition available to the public (lest
they complain about how long it takes), you might put this in a `BUILD.foo`
file and hold back this file when mirroring for the public repository.






