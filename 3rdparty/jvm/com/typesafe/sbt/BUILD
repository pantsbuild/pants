# zinc dependencies

SBT_REV='0.13.8'

jar_library(name = 'compiler-interface',
            jars = [jar(org = 'com.typesafe.sbt', name = 'compiler-interface', rev = SBT_REV,
                        classifier='sources', intransitive=True)],
            dependencies=['//:scala-library'])

jar_library(name = 'incremental-compiler',
            jars = [jar(org = 'com.typesafe.sbt', name = 'incremental-compiler', rev = SBT_REV,
                        intransitive=True)],
            dependencies=[
                '//:scala-compiler',
                '//:scala-library',
                ':sbt-interface'])

jar_library(name = 'sbt-interface',
            jars = [jar(org = 'com.typesafe.sbt', name = 'sbt-interface', rev = SBT_REV,
                    intransitive=True)],
            dependencies=['//:scala-library'])
