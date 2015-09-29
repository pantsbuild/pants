Target(
  name='thrift1',
  sources=[]
)

Target(
  name='thrift2',
  sources=[],
  dependencies=[
    ':thrift1',
  ]
)

Target(
  name='java1',
  sources=[],
  dependencies=[
    ':thrift2',
  ],
  configurations=[
    # TODO(John Sirois): Just use 1 config - this mixed embedded and referenced items just show
    # off / prove the capabilities of the new BUILD graph parser.
    ApacheThriftConfig(
      version='0.9.2',
      strict=True,
      lang='java',
    ),
    ':nonstrict',
    PublishConfig(
      default_repo=':public',
      repos={
        'jake': Config(
          url='https://dl.bintray.com/pantsbuild/maven'
        ),
        'jane': ':public'
      }
    )
  ]
)

ApacheThriftConfig(
  name='nonstrict',
  version='0.9.2',
  strict=False,
  lang='java'
)

Config(
  name='public',
  url='https://oss.sonatype.org/#stagingRepositories'
)