// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
/*
Refer to Jenkins2.0 pipeline and Jenkinsfile docs here:
   https://jenkins.io/doc/pipeline/
   https://jenkins.io/doc/pipeline/jenkinsfile/
   https://jenkins.io/doc/pipeline/steps/
*/

def void ansiColor(Closure<Void> wrapped) {
  wrap([$class: 'AnsiColorBuildWrapper', 'colorMapName': 'XTerm', 'defaultFg': 1, 'defaultBg': 2]) {
    wrapped()
  }
}

def Closure<Void> ciShNodeSpawner(String os, String flags) {
  return { ->
    node(os) {
      ansiColor {
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

// NB: This marks the function as not needing serialization to nodes; ie it runs only on the master.
@NonCPS
def List shardList() {
  List shards = []
  def addShard = { String os, String branchName, String flags ->
    // NB: We use maps instead of a simple `Shard` struct class because the jenkins pipeline
    // security sandbox disallows `new Shard(...)` and offers no way to approve the action.
    // If this could be figured out we could use `List<Shard>` here and in `buildShards` below.
    shards << [os: os, branchName: branchName, flags: flags]
  }

  String changeUrl = env.CHANGE_URL
  println("Listing desired shards for : ${changeUrl}")

  nodes = ['linux': 10]
  isPullRequest = changeUrl ==~ 'https://github.com/pantsbuild/pants/pull/[0-9]+'
  if (!isPullRequest) {
    // We only add OSX to the mix on master commits since our 1 mac-mini is currently a severe
    // throughput bottleneck.
    nodes['osx'] = 2
  }

  nodes.each { os, totalShards ->
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
    shardsByBranch[shard.branchName] = ciShNodeSpawner(shard.os, shard.flags)
  }
  return shardsByBranch
}

Map<String, Closure<Void>> shards = buildShards(shardList())
parallel shards

