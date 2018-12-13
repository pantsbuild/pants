python_library(
  name = 'eval',
  sources = ['eval.py'],
  dependencies = [
    'testprojects/src/antlr/python/test:eval',
  ],
  compatibility='CPython>=2.7,<3'
)

python_binary(
  name = 'eval-bin',
  entry_point = 'antlr.eval',
  dependencies = [
    ':eval',
  ],
  compatibility='CPython>=2.7,<3'
)
