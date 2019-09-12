# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
import os
import stat
import sys

from pants.base.build_environment import get_default_pants_config_file
from pants.engine.fs import FileContent
from pants.option.arg_splitter import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION
from pants.option.config import Config
from pants.option.custom_types import ListValueComponent
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.options import Options
from pants.util.dirutil import read_file
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import SubclassesOf, datatype
from pants.util.strutil import ensure_text


logger = logging.getLogger(__name__)


class OptionsBootstrapper(datatype([
  ('env_tuples', tuple),
  ('bootstrap_args', tuple),
  ('args', tuple),
  ('config', SubclassesOf(Config)),
])):
  """Holds the result of the first stage of options parsing, and assists with parsing full options."""

  @staticmethod
  def get_config_file_paths(env, args):
    """Get the location of the config files.

    The locations are specified by the --pants-config-files option.  However we need to load the
    config in order to process the options.  This method special-cases --pants-config-files
    in order to solve this chicken-and-egg problem.

    Note that, obviously, it's not possible to set the location of config files in a config file.
    Doing so will have no effect.
    """
    # This exactly mirrors the logic applied in Option to all regular options.  Note that we'll
    # also parse --pants-config as a regular option later, but there's no harm in that.  In fact,
    # it's preferable, so that any code that happens to want to know where we read config from
    # can inspect the option.
    flag = '--pants-config-files='
    evars = ['PANTS_GLOBAL_PANTS_CONFIG_FILES', 'PANTS_PANTS_CONFIG_FILES', 'PANTS_CONFIG_FILES']

    path_list_values = []
    if os.path.isfile(get_default_pants_config_file()):
      path_list_values.append(ListValueComponent.create(get_default_pants_config_file()))
    for var in evars:
      if var in env:
        path_list_values.append(ListValueComponent.create(env[var]))
        break

    for arg in args:
      # Technically this is very slightly incorrect, as we don't check scope.  But it's
      # very unlikely that any task or subsystem will have an option named --pants-config-files.
      # TODO: Enforce a ban on options with a --pants- prefix outside our global options?
      if arg.startswith(flag):
        path_list_values.append(ListValueComponent.create(arg[len(flag):]))

    return ListValueComponent.merge(path_list_values).val

  @staticmethod
  def parse_bootstrap_options(env, args, config):
    bootstrap_options = Options.create(
      env=env,
      config=config,
      known_scope_infos=[GlobalOptionsRegistrar.get_scope_info()],
      args=args,
    )

    def register_global(*args, **kwargs):
      ## Only use of Options.register?
      bootstrap_options.register(GLOBAL_SCOPE, *args, **kwargs)

    GlobalOptionsRegistrar.register_bootstrap_options(register_global)
    return bootstrap_options

  @classmethod
  def from_options_parse_request(cls, parse_request):
    return cls.create(env=dict(parse_request.env), args=parse_request.args)

  @classmethod
  def create(cls, env=None, args=None):
    """Parses the minimum amount of configuration necessary to create an OptionsBootstrapper.

    :param env: An environment dictionary, or None to use `os.environ`.
    :param args: An args array, or None to use `sys.argv`.
    """
    env = {k: v for k, v in (os.environ if env is None else env).items()
           if k.startswith('PANTS_')}
    args = tuple(sys.argv if args is None else args)

    flags = set()
    short_flags = set()

    # TODO: This codepath probably shouldn't be using FileContent, which is a very v2 engine thing.
    def filecontent_for(path):
      is_executable = os.stat(path).st_mode & stat.S_IXUSR == stat.S_IXUSR
      return FileContent(
        ensure_text(path),
        read_file(path, binary_mode=True),
        is_executable=is_executable,
      )

    def capture_the_flags(*args, **kwargs):
      for arg in args:
        flags.add(arg)
        if len(arg) == 2:
          short_flags.add(arg)
        elif kwargs.get('type') == bool:
          flags.add('--no-{}'.format(arg[2:]))

    GlobalOptionsRegistrar.register_bootstrap_options(capture_the_flags)

    def is_bootstrap_option(arg):
      components = arg.split('=', 1)
      if components[0] in flags:
        return True
      for flag in short_flags:
        if arg.startswith(flag):
          return True
      return False

    # Take just the bootstrap args, so we don't choke on other global-scope args on the cmd line.
    # Stop before '--' since args after that are pass-through and may have duplicate names to our
    # bootstrap options.
    bargs = tuple(filter(is_bootstrap_option, itertools.takewhile(lambda arg: arg != '--', args)))

    config_file_paths = cls.get_config_file_paths(env=env, args=args)
    config_files_products = [filecontent_for(p) for p in config_file_paths]
    pre_bootstrap_config = Config.load_file_contents(config_files_products)

    initial_bootstrap_options = cls.parse_bootstrap_options(env, bargs, pre_bootstrap_config)
    bootstrap_option_values = initial_bootstrap_options.for_global_scope()

    # Now re-read the config, post-bootstrapping. Note the order: First whatever we bootstrapped
    # from (typically pants.ini), then config override, then rcfiles.
    full_configpaths = pre_bootstrap_config.sources()
    if bootstrap_option_values.pantsrc:
      rcfiles = [os.path.expanduser(str(rcfile)) for rcfile in bootstrap_option_values.pantsrc_files]
      existing_rcfiles = list(filter(os.path.exists, rcfiles))
      full_configpaths.extend(existing_rcfiles)

    full_config_files_products = [filecontent_for(p) for p in full_configpaths]
    post_bootstrap_config = Config.load_file_contents(
      full_config_files_products,
      seed_values=bootstrap_option_values
    )

    env_tuples = tuple(sorted(env.items(), key=lambda x: x[0]))
    return cls(env_tuples=env_tuples, bootstrap_args=bargs, args=args, config=post_bootstrap_config)

  @memoized_property
  def env(self):
    return dict(self.env_tuples)

  @memoized_property
  def bootstrap_options(self):
    """The post-bootstrap options, computed from the env, args, and fully discovered Config.

    Re-computing options after Config has been fully expanded allows us to pick up bootstrap values
    (such as backends) from a config override file, for example.

    Because this can be computed from the in-memory representation of these values, it is not part
    of the object's identity.
    """
    return self.parse_bootstrap_options(self.env, self.bootstrap_args, self.config)

  def get_bootstrap_options(self):
    """:returns: an Options instance that only knows about the bootstrap options.
    :rtype: :class:`Options`
    """
    return self.bootstrap_options

  @memoized_method
  def _full_options(self, known_scope_infos):
    bootstrap_option_values = self.get_bootstrap_options().for_global_scope()
    options = Options.create(self.env,
                             self.config,
                             known_scope_infos,
                             args=self.args,
                             bootstrap_option_values=bootstrap_option_values)

    distinct_optionable_classes = set()
    for ksi in sorted(known_scope_infos, key=lambda si: si.scope):
      if not ksi.optionable_cls or ksi.optionable_cls in distinct_optionable_classes:
        continue
      distinct_optionable_classes.add(ksi.optionable_cls)
      ksi.optionable_cls.register_options_on_scope(options)

    return options

  def get_full_options(self, known_scope_infos):
    """Get the full Options instance bootstrapped by this object for the given known scopes.

    :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
    :returns: A bootrapped Options instance that also carries options for all the supplied known
              scopes.
    :rtype: :class:`Options`
    """
    return self._full_options(tuple(sorted(set(known_scope_infos))))

  def verify_configs_against_options(self, options):
    """Verify all loaded configs have correct scopes and options.

    :param options: Fully bootstrapped valid options.
    :return: None.
    """
    error_log = []
    for config in self.config.configs():
      for section in config.sections():
        if section == GLOBAL_SCOPE_CONFIG_SECTION:
          scope = GLOBAL_SCOPE
        else:
          scope = section
        try:
          valid_options_under_scope = set(options.for_scope(scope))
        # Only catch ConfigValidationError. Other exceptions will be raised directly.
        except Config.ConfigValidationError:
          error_log.append("Invalid scope [{}] in {}".format(section, config.configpath))
        else:
          # All the options specified under [`section`] in `config` excluding bootstrap defaults.
          all_options_under_scope = (set(config.configparser.options(section)) -
                                     set(config.configparser.defaults()))
          for option in all_options_under_scope:
            if option not in valid_options_under_scope:
              error_log.append("Invalid option '{}' under [{}] in {}".format(option, section, config.configpath))

    if error_log:
      for error in error_log:
        logger.error(error)
      raise Config.ConfigValidationError("Invalid config entries detected. "
                              "See log for details on which entries to update or remove.\n"
                              "(Specify --no-verify-config to disable this check.)")
