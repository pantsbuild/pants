# Use globs to group files

## Problem

You're creating a target definition for library, binary, or other target and want to easily group multiple files as source files.

## Solution

Instead of listing files one by one, e.g. `sources=['file1', 'file2', 'file3']`, you can directly 
use globs like `*.java`. To exclude certain files or globs, you can prefix the value with `!`, like `!ignore.java`.

## Discussion

Let's say that you're creating a `scala_library` target definition and you want to include, as sources, all of the `.scala` files contained in the same directory as your `BUILD` file. Here's an example target definition that would accomplish that using a `globs`:

    ::python
    scala_library(
      name='lib',
      sources=['*.scala'],
    )

If you had Scala files in sub-directories that you wanted to include as well, you could use a recursive glob:

    ::python
    scala_library(
      name='lib',
      sources=['**/*.scala'],
    )

You can also exclude files from a particular directory:

    ::python
    scala_library(
      name='lib',
      sources=['**/*.scala', '!dir_to_exclude/**/*.scala'],
    )

## See Also

* [[Create a New Scala or Java Library Target|pants('src/docs/common_tasks:jvm_library')]]
* [[Define a New Python Library Target|pants('src/docs/common_tasks:python_library')]]
