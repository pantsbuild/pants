import urlparse


class MustacheRenderer(object):
  """Renders text using mustache templates."""

  @staticmethod
  def expand(args):
    # Add foo? for each foo in the map that evaluates to true.
    # Mustache needs this, especially in cases where foo is a list: there is no way to render a
    # block exactly once iff a list is not empty.
    # Note: if the original map contains foo?, it will take precedence over our synthetic foo?.
    def convert_val(x):
      # Pystache can't handle sets, so we convert to maps of key->True.
      if isinstance(x, set):
        return dict([(k, True) for k in x])
      elif isinstance(x, dict):
        return MustacheRenderer.expand(x)
      elif isinstance(x, list):
        return [convert_val(e) for e in x]
      else:
        return x
    items = [(key, convert_val(val)) for (key, val) in args.items()]
    ret = dict([(key + '?', True) for (key, val) in items if val and not key.endswith('?')])
    ret.update(dict(items))
    return ret

  def __init__(self, pystache_renderer):
    self._pystache_renderer = pystache_renderer

  def render_name(self, template_name, args):
    return self._pystache_renderer.render_name(template_name, MustacheRenderer.expand(args))

  def render(self, template, args):
    return self._pystache_renderer.render(template, MustacheRenderer.expand(args))

  def render_callable(self, inner_template_name, arg_string, outer_args):
    """Handle a mustache callable.

    In a mustache template, when foo is callable, {{#foo}}arg_string{{/foo}} is replaced with the
    result of calling foo(arg_string). The callable must interpret arg_string.

    This method provides an implementation of such a callable that does the following:
      A) Parses the arg_string as CGI args.
      B) Adds them to the original args that the enclosing template was rendered with.
      C) Renders some other template against those args.
      D) Returns the resulting text.

    Use by adding { 'foo': lambda x: self._renderer.render_callable('foo_template', x, args) }
    to the args of the outer template, which can then contain {{#foo}}arg_string{{/foo}}.
    """
    # First render the arg_string (mustache doesn't do this for you, and it may itself
    # contain mustache constructs).
    rendered_arg_string = self.render(arg_string, outer_args)
    # Parse the inner args as CGI args.
    inner_args = dict([(k, v[0]) for k, v in urlparse.parse_qs(rendered_arg_string).items()])
    # Order matters: lets the inner args override the outer args.
    args = dict(outer_args.items() + inner_args.items())
    # Render.
    return self.render_name(inner_template_name, args)

