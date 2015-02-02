Using Pants with IntelliJ IDEA
==============================

This page documents how to use Pants with [IntelliJ
IDEA](http://www.jetbrains.com/idea/). (To use IntelliJ to work on Pants
*itself*, see
[[Developing Pants with IntelliJ|pants('src/python/pants/docs:intellij')]].)

Pants Build Plugin for IntelliJ
-------------------------------

IntelliJ can ask Pants for information about your code. You can install a Pants-aware IntelliJ
plugin. Once you've done that, you can configure your IntelliJ setup by selecting BUILD targets.
For the details, see the
[IntelliJ-pants-plugin README](https://github.com/pantsbuild/intellij-pants-plugin/blob/master/README.md).

Generating an IDEA Project
--------------------------

If you're using an older Pants (pre-October 2014), then IntelliJ's plugin won't do everything you
need. You'll also need to use Pants to generate an IDEA project.

To generate an IDEA project for the code in `src/java/com/archie/path/to:target` and
`src/java/com/archie/another:target`, use the <a pantsref="oref_goal_idea">idea goal</a>:

    :::bash
    $ ./pants idea src/java/com/archie/path/to:target src/java/com/archie/another:target
