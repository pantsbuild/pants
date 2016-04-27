

def shards = [:]

def ci = "./build-support/bin/ci.sh"

["linux", "osx"].each { os ->

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

  (0..9).each { n ->
    def oneIndexed = n + 1
    shards["${os}_unit_tests_${oneIndexed}_of_10"] = {
      node(os) {
        checkout scm
        sh "${ci} -fkmsrcn -u ${n}/10"
      }
    }
    shards["${os}_integration_tests_${oneIndexed}_of_10"] = {
      node(os) {
        checkout scm
        sh "${ci} -fkmsrjlpn -i ${n}/10"
      }
    }
  }
}

parallel shards
