python_library(
  name='empty',
  sources=rglobs('*.py',
                 exclude=[
                   ['aaa.py', 'dir1/aaa.py'],
                   rglobs('*b.py',
                          exclude=[
                            ['aabb.py'], globs('*/a*.py')
                          ]
                         ),
                   zglobs('**/a.py')
                 ]
                ),
  dependencies=[
  ]
)