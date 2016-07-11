Third-Party Dependencies
========================

Pants has special target types to specify dependencies on external third-party code.
For example, `jar_library` targets point to external JAR files specified using
Maven-style coordinates, and `python_requirements` targets point to external
Python packages using PyPI names and versions.

It's idiomatic to define these external dependencies in BUILD files under a `3rdparty/`
directory. E.g., `3rdparty/jvm/BUILD`, `3rdparty/python/BUILD`.

Keeping all these definitions in one place makes it easier to avoid transitive
dependency conflicts in your codebase.

Note that with this idiom there is no code (source or binary) under `3rdparty`.
There are only BUILD files that tell Pants which versions of which libraries can
be depended on by other code.

* To see how this works in JVM languages, see
  [[JVM 3rdparty Pattern|pants('examples/src/java/org/pantsbuild/example:3rdparty_jvm')]]
* To see how this works in Python, see
  [[Python 3rdparty Pattern|pants('examples/src/python/example:3rdparty_py')]]
