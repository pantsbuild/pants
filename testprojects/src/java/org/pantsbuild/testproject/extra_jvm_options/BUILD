jvm_binary(
    extra_jvm_options=['-Dproperty.color=orange', '-Dproperty.size=2', '-DMyFlag', '-Xmx1m'],
    name='opts',
    main='opts.Main',
    sources=['Main.java']
)

jvm_binary(
    name='noopts',
    main='opts.Main',
    sources=['Main.java']
)

jvm_app(
    name='app_noopts',
    binary=':noopts',
    dependencies=[':noopts'],
)

from os.path import join
python_binary(
    name=join('python_app'),
    source='main.py',
)
