# Create a Bundled zip or Other Archive

## Problem

You're working on a Scala or Java project and you want to bundle your project into a single ZIP file or other archive.

**Note**: If you're working on a Python project, you should compile a Python executable (a `.pex` file) instead of a bundle. More information can be found in [[Run a Binary Target|pants('src/docs/common_tasks:run')]].

## Solution

The `pants bundle` command enables you to bundle a project into a single archive in the following file formats:

* `.zip`
* `.tgz`
* `.tar`
* `.tbz2`

In order to use the `bundle` goal, you need to target a `jvm_app` definition. Here's an example target:

    ::python
    jvm_app(name='bundle',
      basename='my-project-deployable-bundle',
      binary=':my-project-binary-target', # should point to a jvm_binary target
    )

There are two ways to specify the desired file format:

### 1. Through the `BUILD` file (recommended)

Add an `archive` parameter to your `jvm_app` target. Here's an example:

    ::python
    jvm_app(name='bundle',
      archive='zip',
      # etc
    )

### 2. Via the command line (which can override #1)

Add a `--bundle-jvm-archive` option when invoking the Pants executable. Here's an example:

    ::bash
    $ ./pants bundle myproject/subproject:bundle --bundle-jvm-archive=zip

**Note**: If you perform *neither* of the steps explained in #1 and #2, no bundle will be created.

## Discussion

When bundling is complete, you can find the resulting archive in the `dist` directory of your Pants workspace. The name of the `.zip` file is the concatenation of the path to the `BUILD` file and the target name. In this example, the path for the bundle would be `dist/my-project.sub-project.my-project-deployable-bundle.zip` (`my-project.sub-project` is the period-delimited path to the `BUILD` file and `my-project-deployable-bundle` was the `basename` assigned to the target).

## See Also

* [[Define a Scala or Java Library Target|pants('src/docs/common_tasks:jvm_library')]]
