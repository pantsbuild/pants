def ciShNode(String os, String flags) {
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

@NonCPS
def createShard(String os, String branchName, String flags) {
  return [os: os, branchName: branchName, flags: flags]
}

@NonCPS
def List shardList() {
  List shards = []
  ['linux': 10, 'osx': 2].each { os, totalShards ->
    shards << createShard(os, "${os}_self-checks", '-cjlpn')
    shards << createShard(os, "${os}_contrib", '-fkmsrcjlp')

    for (int shard in 0..<totalShards) {
      String shardName = "${shard + 1}_of_${totalShards}"   
      String shardId = "${shard}/${totalShards}"
      shards << createShard(os, "${os}_unit_tests_${shardName}", "-fkmsrcn -u ${shardId}")
      shards << createShard(os, "${os}_integration_tests_${shardName}", "-fkmsrjlpn -i ${shardId}")
    }
  }
  return shards
}

/**
 * Returns a map from pipeline branch name to a callable that allocates a CI node shard.
 */
def Map<String, Closure<Void>> buildShards(List shards) {
  return shards.collectEntries { shard -> [(shard.branchName): ciShNode(shard.os, shard.flags)] }
}

// Now launch all the pipeline steps in parallel.
parallel buildShards(shardList())
