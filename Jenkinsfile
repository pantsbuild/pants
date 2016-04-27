def shards = [:]

def ciShShardedNode(os, flags, typeFlag, shardNum, totalShards) {
  { ->
    node(os) {
      checkout scm
      sh(
        """
        export CXX=g++

        export XDG_CACHE_HOME="\$(pwd)/.cache/pantsbuild"
        echo \$XDG_CACHE_HOME
        
        export PEX_ROOT="\$(pwd)/.cache/pex"
        echo \$PEX_ROOT
        
        ./build-support/bin/ci.sh ${flags} ${typeFlag} ${shardNum}/${totalShards}
        """.toString().stripIndent()
      )
    }
  }
}

def ciShNode(os, flags) {
  { ->
    node(os) {
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

for (os in ["linux", "osx"]) {
  shards["${os}_self-checks"] = ciShNode(os, '-cjlpn')
  shards["${os}_contrib"] = ciShNode(os, '-fkmsrcjlp')

  def totalShards = 10
  for (shardNum in 1..totalShards) {
    def zeroIndexed = shardNum - 1
    shards["${os}_unit_tests_${shardNum}_of_${totalShards}"] = ciShShardedNode(
      os, '-fkmsrcn', '-u', zeroIndexed, totalShards
    )
    shards["${os}_integration_tests_${shardNum}_of_${totalShards}"] = ciShShardedNode(
      os, '-fkmsrjlpn', '-i', zeroIndexed, totalShards
    )
  }
}

parallel shardspe
