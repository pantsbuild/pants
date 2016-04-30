def ciShNode(os, flags) {
  { ->
    node(os) {
      wrap([$class: 'AnsiColorBuildWrapper', 'colorMapName': 'XTerm', 'defaultFg': 1, 'defaultBg': 2]) {
        checkout scm
        sh(
          """
          export CXX=g++

          export XDG_CACHE_HOME="\$(pwd)/.cache/pantsbuild"
          echo \$XDG_CACHE_HOME

          export PEX_ROOT="\$(pwd)/.cache/pex"
          echo \$PEX_ROOT

          ./build-support/bin/ci.sh ${flags}
          """.toString().stripIndent()
        )
      }
    }
  }
}

class Shard {
  String os
  String branchName
  String flags
}

@NonCPS
def shardList() {
  def shards = []
  ['linux': 10, 'osx': 2].each { os, totalShards ->
    shards << new Shard(os: os, branchName: "${os}_self-checks", flags: '-cjlpn')
    shards << new Shard(os: os, branchName: "${os}_contrib", flags: '-fkmsrcjlp')

    for (int shard in 0..<totalShards) {
      String shardName = "${shard + 1}_of_${totalShards}"   
      String shardId = "${shard}/${totalShards}"
      shards << new Shard(os: os,
                          branchName: "${os}_unit_tests_${shardName}",
                          flags: "-fkmsrcn -u ${shardId}")
      shards << new Shard(os: os,
                          branchName: "${os}_integration_tests_${shardName}",
                          flags: "-fkmsrjlpn -i ${shardId}")
    }
  }
  return shards
}

/**
 * Returns a map from pipeline branch name to a callable that allocates a CI node shard.
 */
def buildShards(shards) = shards.collectEntries { [shard.branchName: ciShNode(shard.os, shard.flags)] }

// Now launch all the pipeline steps in parallel.
parallel buildShards(shardList())
