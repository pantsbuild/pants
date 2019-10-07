# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import getpass
import logging
import mimetypes
from os.path import basename
from urllib.parse import quote_plus
from xmlrpc.client import Binary
from xmlrpc.client import Error as XMLRPCError
from xmlrpc.client import ServerProxy


log = logging.getLogger(__name__)


# Copied from `twitter.common.confluence`
# Copyright 2012 Twitter, Inc.

"""Code to ease publishing text to Confluence wikis."""


mimetypes.init()


class ConfluenceError(Exception):
  """Indicates a problem performing an action with confluence."""


class Confluence:
  """Interface for fetching and storing data in confluence."""

  def __init__(self, api_entrypoint, server_url, session_token, content_format='markdown'):
    """Initialize with an established confluence connection."""
    self._api_entrypoint = api_entrypoint
    self._server_url = server_url
    self._session_token = session_token
    self._content_format = content_format

  @staticmethod
  def login(confluence_url, user=None, api_entrypoint='confluence2'):
    """Prompts the user to log in to confluence, and returns a Confluence object.
    :param confluence_url: Base url of wiki, e.g. https://confluence.atlassian.com/
    :param user: Username
    :param api_entrypoint: 'confluence1' or None results in Confluence 3.x. The default
                           value is 'confluence2' which results in Confluence 4.x or 5.x
    :rtype: returns a connected Confluence instance
    raises ConfluenceError if login is unsuccessful.
    """
    server = ServerProxy(confluence_url + '/rpc/xmlrpc')
    user = user or getpass.getuser()
    password = getpass.getpass('Please enter confluence password for %s: ' % user)

    if api_entrypoint in (None, 'confluence1'):
      # TODO(???) didn't handle this JSirois review comment:
      #   Can you just switch on in create_html_page?
      #   Alternatively store a lambda here in each branch.
      api = server.confluence1
      fmt = 'markdown'
    elif api_entrypoint == 'confluence2':
      api = server.confluence2
      fmt = 'xhtml'
    else:
      raise ConfluenceError("Don't understand api_entrypoint %s" % api_entrypoint)

    try:
      return Confluence(api, confluence_url, api.login(user, password), fmt)
    except XMLRPCError as e:
      raise ConfluenceError('Failed to log in to %s: %s' % (confluence_url, e))

  @staticmethod
  def get_url(server_url, wiki_space, page_title):
    """ return the url for a confluence page in a given space and with a given
    title. """
    return '%s/display/%s/%s' % (server_url, wiki_space, quote_plus(page_title))

  def logout(self):
    """Terminates the session and connection to the server.
    Upon completion, the invoking instance is no longer usable to communicate with confluence.
    """
    self._api_entrypoint.logout(self._session_token)

  def getpage(self, wiki_space, page_title):
    """ Fetches a page object.
    Returns None if the page does not exist or otherwise could not be fetched.
    """
    try:
      return self._api_entrypoint.getPage(self._session_token, wiki_space, page_title)
    except XMLRPCError as e:
      log.warning('Failed to fetch page %s: %s' % (page_title, e))
      return None

  def storepage(self, page):
    """Stores a page object, updating the page if it already exists.
    returns the stored page, or None if the page could not be stored.
    """
    try:
      return self._api_entrypoint.storePage(self._session_token, page)
    except XMLRPCError as e:
      log.error('Failed to store page %s: %s' % (page.get('title', '[unknown title]'), e))
      return None

  def removepage(self, page):
    """Deletes a page from confluence.
    raises ConfluenceError if the page could not be removed.
    """
    try:
      self._api_entrypoint.removePage(self._session_token, page)
    except XMLRPCError as e:
      raise ConfluenceError('Failed to delete page: %s' % e)

  def create(self, space, title, content, parent_page=None, **pageoptions):
    """ Create a new confluence page with the given title and content.  Additional page options
    available in the xmlrpc api can be specified as kwargs.
    returns the created page or None if the page could not be stored.
    raises ConfluenceError if a parent page was specified but could not be found.
    """

    pagedef = dict(
      space = space,
      title = title,
      url = Confluence.get_url(self._server_url, space, title),
      content = content,
      contentStatus = 'current',
      current = True
    )
    pagedef.update(**pageoptions)

    if parent_page:
      # Get the parent page id.
      parent_page_obj = self.getpage(space, parent_page)
      if parent_page_obj is None:
        raise ConfluenceError('Failed to find parent page %s in space %s' % (parent_page, space))
      pagedef['parentId'] = parent_page_obj['id']

    # Now create the page
    return self.storepage(pagedef)

  def create_html_page(self, space, title, html, parent_page=None, **pageoptions):
    if self._content_format == 'markdown':
      content = '{html}\n\n%s\n\n{html}' % html
    elif self._content_format == 'xhtml':
      content = '''<ac:macro ac:name="html">
          <ac:plain-text-body><![CDATA[%s]]></ac:plain-text-body>
          </ac:macro>''' % html
    else:
      raise ConfluenceError("Don't know how to convert %s to HTML" % format)
    return self.create(space, title, content, parent_page, **pageoptions)

  def addattachment(self, page, filename):
    """Add an attachment to an existing page.
    Note: this will first read the entire file into memory"""
    mime_type = mimetypes.guess_type(filename, strict=False)[0]
    if not mime_type:
      raise ConfluenceError('Failed to detect MIME type of %s' % filename)

    try:
      with open(filename, 'rb') as f:
        file_data = f.read()

      attachment = dict(fileName=basename(filename), contentType=mime_type)
      return self._api_entrypoint.addAttachment(self._session_token,
                                                page['id'],
                                                attachment,
                                                Binary(file_data))
    except (IOError, OSError) as e:
      log.error('Failed to read data from file %s: %s' % (filename, str(e)))
      return None
    except XMLRPCError:
      log.error('Failed to add file attachment %s to page: %s' %
          (filename, page.get('title', '[unknown title]')))
      return None
