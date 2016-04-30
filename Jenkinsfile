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
def List<Shard> shardList() {
  def shards = []
  ['linux': 10, 'osx': 2].each { os, totalShards ->
    shards << [os: os, branchName: "${os}_self-checks", flags: '-cjlpn'] as Shard
    shards << [os: os, branchName: "${os}_contrib", flags: '-fkmsrcjlp'] as Shard

    for (int shard in 0..<totalShards) {
      String shardName = "${shard + 1}_of_${totalShards}"   
      String shardId = "${shard}/${totalShards}"
      shards << [os: os,
                 branchName: "${os}_unit_tests_${shardName}",
                 flags: "-fkmsrcn -u ${shardId}"] as Shard
      shards << [os: os,
                 branchName: "${os}_integration_tests_${shardName}",
                 flags: "-fkmsrjlpn -i ${shardId}"] as Shard
    }
  }
  return shards
}

/**
 * Returns a map from pipeline branch name to a callable that allocates a CI node shard.
 */
def Map<String, Closure<Void>> buildShards(List<Shard> shards) {
  return shards.collectEntries { shard -> [(shard.branchName): ciShNode(shard.os, shard.flags)] }
}

// Now launch all the pipeline steps in parallel.
parallel buildShards(shardList())
