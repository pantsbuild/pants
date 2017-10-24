# Confluence Utils

The confluence util supplies a way to login and various other CRUD operations.

This module provides a class that wraps the Confluence Wiki API:
`pants.contrib.confluence.util.Confluence`

You can use the `login` classmethod as a constructor:
`pants.contrib.confluence.util.Confluence.login`

Once you have an `Confluence` object you can you use its methods to perform CRUD operations on your wiki:
`pants.contrib.confluence.util.Confluence.get_url`
`pants.contrib.confluence.util.Confluence.getpage`
`pants.contrib.confluence.util.Confluence.storepage`
`pants.contrib.confluence.util.Confluence.removepage`
`pants.contrib.confluence.util.Confluence.create`
`pants.contrib.confluence.util.Confluence.create_html_page`
`pants.contrib.confluence.util.Confluence.addattachment`