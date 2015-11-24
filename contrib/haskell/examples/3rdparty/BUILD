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
