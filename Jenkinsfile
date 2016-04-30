package pants

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

interface Shard {
  def String os()
  def String branchName()
  def String flags()
}

@NonCPS
def Shard createShard(String os, String branchName, String flags) {
  // Script sandboxing under Jenkins does now allow us to define and new-up custom classes;
  // this coercion of a map to a Shard interface works around that.
  return [os: {os}, branchName: {branchName}, flags:{flags}] as Shard
}

@NonCPS
def List<Shard> shardList() {
  def shards = []
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
def Map<String, Closure<Void>> buildShards(List<Shard> shards) {
  return shards.collectEntries { shard ->
    [(shard.branchName()): ciShNode(shard.os(), shard.flags())]
  }
}

// Now launch all the pipeline steps in parallel.
parallel buildShards(shardList())
