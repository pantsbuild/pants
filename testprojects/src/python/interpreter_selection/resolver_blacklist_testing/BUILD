python_binary(
  name='test_bin',
  source='main.py',
  compatibility=['CPython>3'],
  dependencies=[
    ':reqlib'
  ]
)

# Without blacklisting, pex resolver will error out
# on a transitive requirement of jupyter (functools32)
# when resolving for Python 3.
python_requirement_library(
  name='reqlib',
  requirements=[
    python_requirement('jupyter'),
  ]
)
