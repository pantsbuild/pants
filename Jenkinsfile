echo("Test pipeline")
node {
  git url: env.GIT_URL, branch: env.GIT_BRANCH
  sh "./build-support/bin/ci.sh"
}
