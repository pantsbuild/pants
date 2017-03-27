About the documentation
=======================

Pants' user-facing documentation lives in markdown sources, in docstrings, and in some other
special strings. We keep documentation close to the code it describes. If you change some code
and wonder "should I update the docs?" the documentation that needs updating should be nearby.

Docs in the Code
----------------

"Reference" information tends to live in the code. (Information for Pants developers, of course,
lives in docstrings and comments; but some information for Pants *users* lives in the code, too.)

### Goals, tasks, and options

When a user views a goal's options by entering `./pants compile -h` or browsing the
<a pantsref="oref_goal_compile">Pants Options Reference</a>, they see text that "lives" in the
Pants source code. If you [develop a `Task`](dev_tasks.html), document it:

**Goal description:** You can explicitly register a goal's description
using `Goal.register(name, description)`.

This description will default to the description of a task in that goal with the same name
as the goal, if any.

**Task description:** Task descriptions are derived from the first sentence of the docstring
of the task class.

**Option help** When registering a `Task` option, pass a `help` parameter to describe that option.

!inc[start-at=register_options&end-at=help=](../python/pants/core_tasks/list_goals.py)

### Target types and other `BUILD` file symbols

When a user views a target's parameters by entering `./pants targets --details=java_library` or
by browsing the <a pantsref="bdict_java_library">Pants BUILD Dictionary</a>, that information
is derived from the docstrings of the classes implementing those symbols.


Generating the site
-------------------

To see http://www.pantsbuild.org/ site's content as it would be generated based on your local
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
    # proceeding to publish to http://www.pantsbuild.org
    ./build-support/bin/publish_docs.sh -op

If you'd like to publish remotely for others to preview your changes easily, the `-d` option creates
a copy of the site in a subdir of <http://www.pantsbuild.org/>:

    :::bash
    # This publishes the docs locally and opens (-o) them in your browser for review
    # and then prompts you to confirm you want to publish these docs remotely before
    # proceeding to publish to http://www.pantsbuild.org/sirois-test-site
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

You configure this with `src/docs/docsite.json`:

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
