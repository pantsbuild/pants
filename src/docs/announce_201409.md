Hello Pants Build
=================

*Posted September 2014*

As code bases grow, they become increasingly difficult to work with.
Builds get ever slower and existing tooling doesn’t scale. One solution
is to keep splitting the code into more and more independent
repositories. However, as growth continues you end up with hundreds of
free-floating codebases with hard-to-manage dependencies. This makes it
hard to discover, navigate and share code which can impact developer
productivity.

Another solution is to have a single large, unified code base. We’ve
found that this promotes better engineering team cohesion and
collaboration which results in greater productivity and happiness.
However, tooling for such structured code bases has been lacking which
is why we developed [Pants](http://pantsbuild.org/), an open
source build system written in Python.

Pants models code modules (known as “targets”) and their dependencies in
`BUILD` files—in a manner similar to Google's [internal build
system](http://google-engtools.blogspot.com/2011/08/build-in-cloud-how-build-system-works.html).
This allows it to only build the parts of the codebase you actually
need, ignoring the rest of the code. This is a key requirement for
scaling large, unified code bases.

Pants started out in 2010 as an internal tool at
[Twitter](https://twitter.com/) and was originally just a frontend to
generate `build.xml` files for the Ant build tool, hence the name (a
contraction of “Python Ant”). Pants grew in capability and complexity,
and became the build tool for the
[twitter/commons](https://github.com/twitter/commons/) open source
libraries, and hence became open source itself.

In 2012, [Foursquare](https://foursquare.com/) began using Pants
internally, and Foursquare engineers picked up the Pants development
mantle, adding Scala support, build artifact caching and many other
features.

Since then several other engineering teams, including those at [Urban
Compass](https://www.urbancompass.com/) and
[Oscar](https://www.hioscar.com/?locale=en), have integrated Pants into
their codebases. Most recently, [Square](https://squareup.com/) began to
use Pants and has also contributed significantly to its development.

As a result, Pants is a true independent open source project with
collaborators across companies and a growing development community. It
now lives in a standalone repo at <https://github.com/pantsbuild/pants>.

Among Pants’s current strengths are:

-   Builds [Java](http://pantsbuild.org/JVMProjects.html), Scala,
    and [Python](http://pantsbuild.org/python-readme.html).
-   Adding support for new languages is straightforward.
-   Supports code generation:
    [thrift](http://pantsbuild.org/ThriftDeps.html), protocol
    buffers, custom code generators.
-   Resolves external JVM and Python dependencies.
-   Runs tests.
-   Spawns Python and Scala REPLs with appropriate load paths.
-   Creates deployable packages.
-   Scales to large repos with many interdependent modules.
-   Designed for incremental builds.
-   Support for local and distributed caching.
-   Especially fast for Scala builds, compared to alternatives.
-   Builds standalone python executables ([PEX
    files](https://pex.readthedocs.io/))
-   Has a plugin system to add custom features and override stock
    behavior.
-   Runs on Linux and Mac OS X.

Since moving Pants to its own GitHub organization, our [commit
rate](https://github.com/pantsbuild/pants/graphs/contributors) has grown
and we’ve welcomed more committers to the project.

If your codebase is growing beyond your toolchain’s ability to scale,
but you’re reluctant to split it up, you might want to give Pants a try.
It may be of particular interest if you have complex dependencies,
generated code and custom build steps.

Pants is still a young and evolving open source project. We constantly
strive to make it easier to use. If you’re interested in using or
learning from Pants, our advice is to reach out to the community on the
[developer mailing
list](http://pantsbuild.org/howto_contribute.html) and follow
[@pantsbuild](https://twitter.com/pantsbuild) on Twitter for updates.

**Organization Perspectives:**

-   [Introducing Pants: a build system for large-scale codebases like
    Foursquare’s](http://engineering.foursquare.com/2014/09/16/introducing-pants-a-build-system-for-large-scale-codebases-like-foursquares/),
    Foursquare Engineering Blog
-   [Trying on
    Pants](http://corner.squareup.com/2014/09/trying-on-pants.html),
    Eric Ayers, Infrastructure/Shared Systems team engineer / Square
    Engineering Blog

