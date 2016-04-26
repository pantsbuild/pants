

def shards = [:]

shards["unit1"] = {
  node {
    checkout scm
    sh "./build-support/bin/ci.sh -fkmsrcn -u 0/2 'Unit tests for pants and pants-plugins - shard 1'"
  }
}

shards["unit2"] = {
  node {
    checkout scm
    sh "./build-support/bin/ci.sh -fkmsrcn -u 1/2 'Unit tests for pants and pants-plugins - shard 2'"
  }
}

parallel shards
