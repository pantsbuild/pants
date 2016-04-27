

def shards = [:]

def ci = "./build-support/bin/ci.sh"
def allOSes = ["linux", "osx"]

for (int i = 0; i < allOSes.size(); i++) {
  def os = allOSes.get(i)
  shards["${os}_self-checks"] = {
    node(os) {
      checkout scm
      sh "${ci} -cjlpn"
    }
  }

  shards["${os}_contrib"] = {
    node(os) {
      checkout scm
      sh "${ci} -fkmsrcjlp"
    }
  }

  def totalShards = 10
  for (int shardNum = 0; shardNum < totalShards; shardNum++) {
    def oneIndexed = shardNum + 1
    shards["${os}_unit_tests_${oneIndexed}_of_10"] = {
      node(os) {
        checkout scm
        sh "${ci} -fkmsrcn -u ${shardNum}/10"
      }
    }
    shards["${os}_integration_tests_${oneIndexed}_of_10"] = {
      node(os) {
        checkout scm
        sh "${ci} -fkmsrjlpn -i ${shardNum}/10"
      }
    }
  }
}

parallel shards
