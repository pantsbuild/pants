python_binary(
  name='test_bin',
  source='main.py',
  compatibility=['CPython>=3.6'],
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
    # NB: jupyter 1.0.0 does not properly pin its dep graph and both ipykernel and ipython support
    # python 3 only post 5 and 6 respectively; so we add those deps explictly only to constrain them
    # low such that they support python 2.7 for this test.
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
