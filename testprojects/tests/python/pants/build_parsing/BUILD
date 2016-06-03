# N.B. This is used by an integration test to validate global scope binding in BUILD-file parsing.

PREFIX = 'test'

def generate_name(name):
  return '{}-{}'.format(PREFIX, name)

target(
  name=generate_name('nested-variable-access-in-function-call')
)
