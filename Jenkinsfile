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

// Build up a map from pipeline step name to a callable that allocates a node for the step.
def shards = [:]

for (os in ['linux', 'osx']) {
  shards["${os}_self-checks"] = ciShNode(os, '-cjlpn')
  shards["${os}_contrib"] = ciShNode(os, '-fkmsrcjlp')

  int totalShards = 10
  for (int shard in 0..<totalShards) {
    String shardName = "${shard + 1}_of_${totalShards}"   
    String shardId = "${shard}/${totalShards}"
    shards["${os}_unit_tests_${shardName}"] = ciShNode(os, "-fkmsrcn -u ${shardId}")
    shards["${os}_integration_tests_${shardName}"] = ciShNode(os, "-fkmsrjlpn -i ${shardId}")
  }
}

// Now launch all the pipeline steps in parallel.
parallel shards
