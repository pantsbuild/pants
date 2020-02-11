java_thrift_library(
  name='thrift-java',
  sources=['**/*.thrift'],
  compiler='scrooge',
  language='java',
  # NB: this setting is a temporary way to get tests passing, as Scrooge and Thrift
  # require JDK 8 to function properly. This constraint should really be specified in
  # source code, not in test BUILD files. See #6956
  platform='java8',
)
