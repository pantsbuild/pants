# N.B. This is used by an integration test to validate global scope binding in BUILD-file parsing.

PREFIX = 'test'

def generate_name(name):
  return '{}_{}'.format(PREFIX, name)

target(
  name=generate_name('nested_variable_access_in_function_call')
)
