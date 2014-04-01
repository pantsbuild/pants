#######################
Python 3rdparty Pattern
#######################

In general, we use :doc:`the 3rdparty idiom <3rdparty>` to organize
dependencies on code from outside the source tree. This document
describes how to make this work for Python code.

Your Python code can pull in code written elsewhere. Pants fetches code
via a library that uses pip-style specifications (name and version-range).

***************
3rdparty/python
***************

**The Python part of 3rdparty is in 3rdparty/python/BUILD**.

In this ``BUILD`` file, you want a ``python_requirement`` like::

    python_requirement(name="beautifulsoup",
                       requirement="BeautifulSoup==3.2.0")

.. TODO existing python sample code doesn't have a 3rdparty requirement;
   cobbled this example together from non-exemplary code

**********************
Your Code's BUILD File
**********************

In your code's ``BUILD`` file, introduce a dependency on the ``3rdparty``
target::

    # src/python/scrape_html/BUILD
    python_binary(name = "scrape_html",
      source = "scrape_html.py",
      dependencies = [
        pants('3rdparty/python:beautifulsoup'),
      ]
    )

Then in your Python code, you can ``import`` from that package::

    # src/python/scrape_html/scrape_html.py
    from BeautifulSoup import BeautifulSoup
