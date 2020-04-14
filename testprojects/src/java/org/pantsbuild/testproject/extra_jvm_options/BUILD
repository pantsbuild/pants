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

python_binary(
    name='python_app',
    sources=['main.py'],
)
