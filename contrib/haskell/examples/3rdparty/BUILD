haskell_stackage_package(
  name='pipes',
)

haskell_stackage_package(
  name='mmorph',
)

haskell_hackage_package(
  name='promises',
  version='0.2',
)

haskell_hackage_package(
  name='discrimination',
  version='0.1',
  dependencies=[
    ':promises'
  ],
)

haskell_project(
  name='headless-project',
  resolver='lts-3.1',
  dependencies=[
    ':discrimination',
    ':mmorph',
    ':pipes',
  ],
)

haskell_source_package(
  name='lens-family-core',
  path='http://hackage.haskell.org/package/lens-family-core-1.2.0/lens-family-core-1.2.0.tar.gz',
)

haskell_project(
  name='lens-family-core-project',
  resolver='lts-3.1',
  dependencies=[
    ':lens-family-core',
  ]
)
