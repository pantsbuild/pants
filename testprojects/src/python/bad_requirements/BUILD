python_requirement_library(
  name='badreq',
  requirements=[
    python_requirement('badreq==99.99.99')
  ]
)

python_binary(
  name='use_badreq',
  dependencies=[':badreq'],
  entry_point='bad_requirements.use_badreq',
)
