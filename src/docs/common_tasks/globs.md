# Use globs and rglobs to Group Files

## Problem

You're creating a target definition for library, binary, or other target and want to easily group multiple files as source files.

## Solution

Instead of listing files one by one, e.g. `sources=['file1', 'file2', 'file3']`, you can specify either a `globs` or an `rglobs`.

## Discussion

Let's say that you're creating a `scala_library` target definition and you want to include, as sources, all of the `.scala` files contained in the same directory as your `BUILD` file. Here's an example target definition that would accomplish that using a `globs`:

    ::python
    scala_library(name='scala',
      sources=globs('*.scala'),
    )

If you had Scala files in sub-directories that you wanted to include as well, you could use an `rglobs`:

    ::python
    scala_library(name='scala',
      sources=rglobs('*.scala'),
    )

You can also exclude files from a particular directory:

    ::python
    scala_library(name='scala',
      sources=rglobs('*.scala', exclude=[rglobs('dir_to_exclude/*.scala')]),
    )

## See Also

* [[Create a New Scala or Java Library Target|pants('src/docs/common_tasks:jvm_library')]]
* [[Define a New Python Library Target|pants('src/docs/common_tasks:python_library')]]
