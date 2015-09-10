README Files and Markdown
=========================

You can write program documentation in the popular Markdown or ReST format;
Pants eases publishing your docs to places where your users can read it.
E.g., that `README.md` file in your source code is handy for editing;
but you might want to generate a web page from that so folks can decide
whether they want to look at your source code.

Markdown to HTML
----------------

To tell Pants about your Markdown or ReST file, use a
<a pantsref="bdict_page">`page`</a>
target in a `BUILD` file as in this excerpt from
[examples/src/java/org/pantsbuild/example/hello/main/BUILD](https://github.com/pantsbuild/pants/blob/master/examples/src/java/org/pantsbuild/example/hello/main/BUILD):

!inc[start-after=README page](hello/main/BUILD)

To render the page as HTML, use the
<a pantsref="oref_goal_markdown">markdown goal</a>. For example, to view
`examples/src/java/org/pantsbuild/example/hello/main/README.md` as HTML in
your browser,

    :::bash
    $ ./pants markdown --open examples/src/java/org/pantsbuild/example/hello/main:readme

Pants generates the HTML files in the `dist/markdown/` directory tree.

Markdown Syntax
---------------

Pants uses the Python `Markdown` module; thus, in addition to the usual
Gruber `Markdown` syntax, there are [other
features](http://pythonhosted.org/Markdown/) Pants uses Python
Markdown's `codehilite`, `extra`, `tables`, and `toc` extensions.

### Link to Another `page`

One `page` can link to another. Regular Markdown-link syntax works for
regular links; but if you use `page`s to generate both `.html` files and
wiki pages, it's not clear what to link to: the `.html` file or the wiki
address. You can use a Pants-specific syntax to make links that work
with generated HTML or wiki pages.

To set up a page `source.md` that contains a link to `dest.md`, you make
a `dependencies` relation and use the special `pants(...)` syntax in the
markdown.

In the `BUILD` file:

    :::python
    page(name='source',
      source='source.md',
      dependencies=[':dest'], # enables linking
      provides=[...publishing info...],
    )

    page(name='dest',
      source='dest.md',
      provides=[...publishing info...],
    )

To set up the links in `source.md` that point to `dest.md` or an anchor
therein:

    For more information about this fascinating topic,
    please see [[Destinations|pants('path/to:dest')]],
    especially the
    [[Addendum section|pants('path/to:dest)'#addendum]],

Pants replaces the `pants('path/to:dest')` with the appropriate link.

### Include a File Snippet

Sometimes the best way to explain `HelloWorld.java` is to show an
excerpt from `HelloWorld.java`. You can use the `!inc` markdown to do
this. Specify a file to include and (optionally) regexps at which to
start copying or stop copying. For example, to include an excerpt from
the file `HelloMain.java`, starting with the first line matching the
pattern `void main` and stopping before a subsequent line matching
`private HelloMain`:

    !inc[start-at=void main&end-before=private HelloMain](HelloMain.java)

To include *all* of `HelloMain.java`:

    !inc(HelloMain.java)

To include most of `HelloMain.java`, starting after license boilerplate:

    !inc[start-after=Licensed under the Apache](HelloMain.java)

It accepts the following optional parameters, separated by ampersands
(&):

start-at=*substring*<br>
When excerpting the file to include, start at the first line containing
*substring*.

start-after=*substring*<br>
When excerpting the file to include, start after the first line
containing *substring*.

end-before=*substring*<br>
When excerpting the file to include, stop before a line containing
*substring*.

end-at=*substring*<br>
When excerpting the file to include, stop at a line containing
*substring*.

ReStructedText Syntax
---------------------

Pants can generate web content from
[docutils reStructuredText](http://docutils.sourceforge.net/rst.html)-formatted text.

To tell Pants that your `page` target's source is in reStructuredText format, you can either

* give the `source` file an `.rst` file extension, or
* pass `format='rst'` to the `page` target.

Publishing
----------

You can tell Pants to publish a page. So far, there's only one way to
publish: as a page in an Atlassian Confluence wiki. (You can add other
doc-publish backends to Pants;
[[send us a patch|pants('src/python/pants/docs:howto_contribute')]]!)

To specify the "address" to which to publish a page, give it a
`provides` parameter.

Once you've done this, you can publish the page by invoking the goal
<a pantsref="page_setup_confluence">set up in your workspace</a>. For example, if
the goal was set up with the name "confluence", you invoke:

    :::bash
    $ ./pants confluence examples/src/java/org/pantsbuild/example/hello/main:readme

To specify that a page should be published to a Confluence wiki page,
set its `provides` to something like:

    :::python
    page(...
      provides=[
        wiki_artifact(wiki=confluence,
          space='ENG',
          title='Pants Hello World Example',
          parent='Examples',
        )
      ],)

...assuming your workspace is set up for confluence publishing with a `Wiki` symbol named
`confluence` set up as part of a plugin as described below:

<a pantsmark="page_setup_confluence"></a>

**Setting up your workspace for Confluence publish**

That `wiki` specifies some information about your wiki server. So far, the only kind of thing you
can publish to is a Confluence wiki. To set up and register this symbol, set up a
[[Pants plugin|pants('src/python/pants/docs:howto_plugin')]] if your workspace doesn't already
have one. In the plugin, define a `Wiki` and register it:

    :::python
    import urllib

    from pants.backend.core.targets.doc import Wiki

    def confluence_url_builder(page, config):
      title = config['title']
      return title, 'https://wiki.archie.org/display/%s/%s' % (
        config['space'],
        urllib.quote_plus(title))

    confluence_wiki = Wiki(name='confluence', url_builder=confluence_url_builder)

    # in register.py:
    def build_file_aliases():
      return BuildFileAliases(
        # ...
        objects={
          # ...
          'confluence', confluence_wiki},
      )

You need to install a goal to enable publishing a doc to confluence. To do this, in your Pants
plugin, install a goal that subclasses `ConfluencePublish`:

    :::python
    from pants.backend.core.tasks.confluence_publish import ConfluencePublish

    class ArchieConfluence(ConfluencePublish):
      def wiki(self):
        return confluence_wiki
      def api(self):
        return 'confluence2'

    # in register.py:
    def register_goals():
      # ...
      task(name='confluence', action=ArchieConfluence, dependencies=['markdown']).install()

In your `pants.ini` file, add a section with the url of your wiki server. E.g., if your server
is at wiki.archie.org, it would look like:

    [confluence]
    url: https://wiki.archie.org
