python_library(
  name = 'eval',
  sources = ['eval.py'],
  dependencies = [
    'testprojects/src/antlr/python/test:eval',
  ],
)

python_binary(
  name = 'eval-bin',
  entry_point = 'antlr.eval',
  dependencies = [
    ':eval',
  ],
)
