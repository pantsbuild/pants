About the documentation
=======================

Pants' user-facing documentation lives in markdown sources, in docstrings, and in some other
special strings. We keep documentation close to the code it describes. If you change some code
and wonder "should I update the docs?" the documentation that needs updating should be nearby.

Docs in the Code
----------------

"Reference" information tends to live in the code. (Information for Pants developers, of course,
lives in docstrings and comments; but some information for Pants *users* lives in the code, too.)

### Goals, Tasks, and Options

When a user views a goal's options by entering `./pants compile -h` or browsing the
<a pantsref="oref_goal_compile">Pants Options Reference</a>, they see text that "lives" in the
Pants source code. If you [develop a `Task`](dev_tasks.html), document it:

**Goal description:** If a goal will have multiple tasks in it, register its description
using `Goal.register(name, description`.

In the common case where a goal will contain only a single task with the same name as the goal,
the goal will default to using the first sentence of the task's docstring as its description.

**Option help** When registering a `Task` option, pass a `help` parameter to describe that option.

!inc[start-at=register_options&end-at=help=](../core_tasks/list_goals.py)

### Targets and other `BUILD` File Things

When a user views a target's parameters by entering `./pants targets --details=java_library` or
by browsing the <a pantsref="bdict_java_library">Pants BUILD Dictionary</a>, they're mostly
seeing information from a docstring. Pants extracts the useful information with some reflection
code.

In a few cases, the reflection code doesn't do the right thing without some "steering". E.g.,
a Target is implemented by a Python class. *Most* of those class' methods aren't useful in
`BUILD` files, but a few are. To reveal only the useful methods in the docs, Pants omits them
by default, except those that have been tagged for inclusion.

To "steer" the reflection, use a `@manual.builddict` annotation. See its
[docstring](https://github.com/pantsbuild/pants/blob/master/src/python/pants/base/build_manual.py)
for details about what it can show/hide.

Generating the site
-------------------

To see http://pantsbuild.github.io/ site's content as it would be generated based on your local
copy of the pants repo, enter the command

    :::bash
    # This publishes the docs **locally** and opens (-o) them in your browser for review
    ./build-support/bin/publish_docs.sh -o

Publishing the site
-------------------

We publish the site via [Github Pages](https://pages.github.com/). You need `pantsbuild` commit
privilege to publish the site.

Use the same script as for generating the site, but request it also be published. Don't
worry—you'll get a chance to abort the publish just before it's committed remotely:

    :::bash
    # This publishes the docs locally and opens (-o) them in your browser for review
    # and then prompts you to confirm you want to publish these docs remotely before
    # proceeding to publish to http://pantsbuild.github.io
    ./build-support/bin/publish_docs.sh -op

If you'd like to publish remotely for others to preview your changes easily, the `-d` option creates
a copy of the site in a subdir of <http://pantsbuild.github.io/>:

    :::bash
    # This publishes the docs locally and opens (-o) them in your browser for review
    # and then prompts you to confirm you want to publish these docs remotely before
    # proceeding to publish to http://pantsbuild.github.io/sirois-test-site
    ./build-support/bin/publish_docs.sh -opd sirois-test-site

Cross References
----------------

If your doc has a
link like `<a pantsref="bdict_java_library">java_library</a>`, it links to
the BUILD Dictionary entry for `java_library`. To set up a short-hand
link like this...

Define the destination of the link with an `pantsmark` anchor, e.g.,
`<a pantsmark="bdict_java_library"> </a>`. The `pantsmark` attribute (here,
`bdict_java_library`) must be unique within the doc set.

Link to the destination with an `pantsref`, e.g.,
`<a pantsref="bdict_java_library">java_library</a>`.

Doc Site Config
---------------

The site generator
takes "raw" `.html` files, "wraps" them in a template with some
navigation UI, and writes out the resulting `.html` files.

You configure this with `src/python/pants/docs/docsite.json`:

`sources`:<br>
Map of pages to the `.html` files they're generated from. E.g.,
`"build_dictionary": "dist/builddict/build_dictionary.html",` means to
generate the site's /build\_dictionary.html page, the site generator
should get the "raw" file `dist/builddict/build_dictionary.html` and
apply the template to it.

`tree`:<br>
Outline structure of the site. Each node of the tree is a dict. Each
node-dict can have a `page`, a page defined in `sources` above. Each
node-dict can have a `children`, a list of more nodes.

`template`:<br>
Path to mustache template to apply to each page.

`extras`:<br>
Map of "extra" files to copy over. Handy for graphics, stylesheets, and
such.

`outdir`:<br>
Path to which to write the generated site.

To add a page and have it show up in the side navigation UI, add the
page to the `sources` dict and to the `tree` hierarchy.
