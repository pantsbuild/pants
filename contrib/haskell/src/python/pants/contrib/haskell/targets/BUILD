target(
  name='targets',
  dependencies=[
    ':stackage',
    ':hackage',
    ':cabal',
  ]
)

python_library(
  name='stackage',
  sources=[
    'stackage.py',
  ],
  dependencies=[
    ':haskell_package',
  ]
)

python_library(
  name='hackage',
  sources=[
    'hackage.py',
  ],
  dependencies=[
    ':haskell_package',
  ]
)

python_library(
  name='cabal',
  sources=[
    'cabal.py',
  ],
  dependencies=[
    ':haskell_package',
  ]
)

python_library(
  name='haskell_package',
  sources=[
    'haskell_package.py',
  ],
  dependencies=[
    'src/python/pants/base:target'
  ],
)
