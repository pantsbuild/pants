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
  name='stack',
  path='https://github.com/commercialhaskell/stack/archive/v0.1.3.1.tar.gz',
)

haskell_project(
  name='stack-project',
  resolver='lts-3.1',
  dependencies=[
    ':stack',
  ]
)
