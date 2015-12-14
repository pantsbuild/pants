# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

Target(
  name='thrift1',
)

Target(
  name='thrift2',
  dependencies=[
    ':thrift1',
  ]
)

# Right now the base Config class only allows either `extends` or `merges`, but more complex chains
# can always be built up via a sequence of objects extending or merging others.
Target(
  name='java1',
  merges=[':production_thrift_configs'],
  sources={},
  dependencies=[
    ':thrift2',
  ],
  configurations=[
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
  extends=':production_thrift_config',
  strict=False,
  lang='java'
)

Config(
  name='public',
  url='https://oss.sonatype.org/#stagingRepositories'
)

# ~ABCs defined in a BUILD - no plugin needed for extending target types.
#
# This also solves the extracted constant version for jar libraries for example:
# Jar(org='org.apache.lucene', name='production_lucene_jar', rev='5.3.1')
#
# Jar(extends=':production_lucene_jar', name='lucene-core')
# Jar(extends=':production_lucene_jar', name='lucene-codecs')
# Jar(extends=':production_lucene_jar', name='lucene-classification')
#
# Note also that the ancient pants support for inline jar dependencies can be resurrected.  No
# longer must a dependency by thing with dependencies itself (JarLibrary) - it can be an addressable
# leaf.  This allows for much more natural very small project setups with pants.  You have 1 small
# target with all configuration inline.

ApacheThriftConfig(
  name='production_thrift_config',
  abstract=True,  # ApacheThriftConfig validates, so we avoid validation for this abstract template.
  version='0.9.2',
  strict=True

  # NB: This abstract template has no `lang` - which is required (validated).
)

# Since this abstract target declares a list, it can be usefully extended via `merges` such that
# additional configurations defined by the merger are appended.
Target(
  name='production_thrift_configs',
  configurations=[
    # TODO(John Sirois): Just use 1 config - this mixed embedded and referenced items just show
    # off / prove the capabilities of the new BUILD graph parser.
    ApacheThriftConfig(
      version='0.9.2',
      strict=True,
      lang='java',
    ),
    ':nonstrict'
  ]
)
