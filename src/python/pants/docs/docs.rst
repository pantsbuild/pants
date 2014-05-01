=======================
About the documentation
=======================

Pants documentation is generated from `reStructuredText`_ sources by `Sphinx`_,
the tool Python itself is documented with. This site was modeled on
the `Python documentation`_.

.. _reStructuredText: http://docutils.sf.net/rst.html
.. _Sphinx: http://sphinx.pocoo.org/
.. _Python Documentation: http://docs.python.org

-------------------
Generating the site
-------------------

A script encapsulates all that needs to be done.  To generate and preview changes, just::

   # This publishes the docs **locally** and opens (-o) them in your browser for review
   ./build-support/bin/publish_docs.sh -o

-------------------
Publishing the site
-------------------

Use the same script as for generating the site, but request it also be published.  Don't
worry - you'll get a chance to abort the publish just before its comitted remotely::

   # This publishes the docs locally and opens (-o) them in your browser for review
   # and then prompts you to confirm you want to publish these docs remotely before
   # proceeding to publish to http://pantsbuild.github.io
   ./build-support/bin/publish_docs.sh -op

If you'd like to publish remotely for others to preview your changes easily, there is a
-d option that will create a copy of the site in a subdir of http://pantsbuild.github.io/ ::

  # This publishes the docs locally and opens (-o) them in your browser for review
  # and then prompts you to confirm you want to publish these docs remotely before
  # proceeding to publish to http://pantsbuild.github.io/sirois-test-site
  ./build-support/bin/publish_docs.sh -opd sirois-test-site
