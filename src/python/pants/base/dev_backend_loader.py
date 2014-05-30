

def load_backends_from_source(build_file_parser):
  print("Loading pants backends from source")
  backend_packages = [
    'pants.backend.core',
    'pants.backend.python',
    'pants.backend.jvm',
    'pants.backend.codegen',
    'pants.backend.maven_layout',
  ]
  for backend_package in backend_packages:
    module = __import__(backend_package + '.register',
                        {}, # globals
                        {}, # locals
                        [
                          'target_aliases',
                          'object_aliases',
                          'applicative_path_relative_util_aliases',
                          'partial_path_relative_util_aliases',
                          'commands',
                          'goals',
                        ])
    for alias, target_type in module.target_aliases().items():
      build_file_parser.register_target_alias(alias, target_type)

    for alias, obj in module.object_aliases().items():
      build_file_parser.register_exposed_object(alias, obj)

    for alias, util in module.applicative_path_relative_util_aliases().items():
      build_file_parser.register_applicative_path_relative_util(alias, util)

    for alias, util in module.partial_path_relative_util_aliases().items():
      build_file_parser.register_partial_path_relative_util(alias, util)

    module.register_commands()
    module.register_goals()
