# Create a Resource Bundle

## Problem

You have resources such as JSON or YAML config files, Bash scripts, or other assets that you want to combine into a resource bundle that can be used by other Pants targets.

## Solution

Create a `resources` target that tells Pants which files to include in the resource bundle.

## Discussion

A `resources` target definition must include a `name` and a list of `sources`, which is a simple list of file names. This would create a resource bundle with two files:

    ::python
    resources(
      name='config'
      sources=['server-config.yaml', 'logging-config.xml'],
    )

This would include a recursive glob of files to a resource bundle:

    ::python
    resources(
      name='templates',
      sources=['**/*.mustache'],
    )

This would include a mixture of globs, recursive globs, and specific files:

    ::python
    resources(
      name='all'
      sources=['*.json', 'templates/**/*', 'logback.xml'],
    )

You can also exclude files and globs by prefixing them with `!`:

    ::python
    resources(
      name='python-resources',
      sources=['**/*', '!**/*.pyc'],
    )

Once your resource bundle has been specified, you can depend on it from the target that consumes the resources:

    ::python
    java_library(
      name='server',
      sources=['*.java'],
      dependencies=[
        'src/resources:config',
      ]
    )

This dependency ensures that the files in the resource bundle will be present at runtime (e.g.,
for JVM binaries, they will be included on the runtime classpath).

## See Also

* [[Create a Bundled zip or Other Archive|pants('src/docs/common_tasks:bundle')]]
