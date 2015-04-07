Third-Party Dependencies
========================

Despite your best recruiting efforts, most software is still written by
people outside your organization. Your code can import some of this
*third-party* code. In the usual Pants way, a build target *depends* on
something to enable importing its code. Special dependencies represent
third-party code.

To help all your code depend on the same version of third-party code,
it's handy to keep these special dependencies in one place in your
source tree. By convention, Pants-using source trees use a `3rdparty/`
directory to hold these dependencies.

If two parts of your code depend on two versions of the same package,
some tool will pick one version to use. The behavior depends on the
tool, but you can be sure that one part of your code is *not* using the
version it expects. This is known as a *diamond dependencies problem*,
*dependencies version conflict*, or *dependency hell*; you don't want
it.

By keeping external dependencies in one place, you make it easier for
all your code to depend on the same version and avoid surprises.

Beware: some version dependencies "hide." You depend on an external
packages; an external package itself depends on others and "knows" what
versions of those packages it depends on. Even though all your code
depends on the version specified in `3rdparty/`, you might depend on
something which, in turn, depends on some other version.

* For see how this works in JVM languages, see
  [[JVM 3rdparty Pattern|pants('examples/src/java/org/pantsbuild/example:3rdparty_jvm')]]
* For see how this works in Python, see
  [[Python 3rdparty Pattern|pants('examples/src/python/example:3rdparty_py')]]
