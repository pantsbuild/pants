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
def List shardList() {
  List shards = []
  def addShard = { String os, String branchName, String flags ->
    shards << [os: os, branchName: branchName, flags: flags]
  }

  ['linux': 10, 'osx': 2].each { os, totalShards ->
    addShard(os, "${os}_self-checks", '-cjlpn')
    addShard(os, "${os}_contrib", '-fkmsrcjlp')

    for (int shard in 0..<totalShards) {
      String shardName = "${shard + 1}_of_${totalShards}"   
      String shardId = "${shard}/${totalShards}"
      addShard(os, "${os}_unit_tests_${shardName}", "-fkmsrcn -u ${shardId}")
      addShard(os, "${os}_integration_tests_${shardName}", "-fkmsrjlpn -i ${shardId}")
    }
  }
  return shards
}

def Map<String, Closure<Void>> buildShards(List shards) {
  Map<String, Closure<Void>> shardsByBranch = [:]
  for (shard in shards) {
    shardsByBranch[shard.branchName] = ciShNode(shard.os, shard.flags)
  }
  return shardsByBranch
}

Map<String, Closure<Void>> shards = buildShards(shardList())
parallel shards

