python_binary(
  name='test_bin',
  source='main.py',
  compatibility=['CPython>=3.6'],
  dependencies=[
    ':reqlib'
  ]
)

# This library requires pex blacklisting under python 3, because the pex resolver will error out
# on a transitive requirement of jupyter (functools32).
#
# This test also runs under python 2 though, and so in order to avoid dep floats of jupyter's
# transitive deps (which can float upward to versions that do not support python 2), we pin them.
python_requirement_library(
  name='reqlib',
  requirements=[
    python_requirement('jupyter==1.0.0'),
    python_requirement('ipykernel<5'),
    python_requirement('ipython<6'),
  ]
)

# Test non-blacklisted backport usage.
python_binary(
  name='test_py2',
  source='import_futures.py',
  compatibility=['CPython<3'],
  dependencies=[
    ':futures_reqlib'
  ]
)

python_requirement_library(
  name='futures_reqlib',
  requirements=[
    python_requirement('futures'),
  ]
)
