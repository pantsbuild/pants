`twitter.common.confluence`
===========================

.. py:module:: twitter.common.confluence

This module provides a class that wraps the Confluence Wiki API.

.. autoclass:: twitter.common.confluence.Confluence

You can use the `login` classmethod as a constructor

.. automethod:: twitter.common.confluence.Confluence.login

Once you have an `Confluence` object you can you use its methods to perform CRUD operations on your wiki.


.. automethod:: twitter.common.confluence.Confluence.get_url
.. automethod:: twitter.common.confluence.Confluence.getpage
.. automethod:: twitter.common.confluence.Confluence.storepage
.. automethod:: twitter.common.confluence.Confluence.removepage
.. automethod:: twitter.common.confluence.Confluence.create
.. automethod:: twitter.common.confluence.Confluence.create_html_page
.. automethod:: twitter.common.confluence.Confluence.addattachment