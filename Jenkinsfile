echo("Test pipeline")
echo("${env.GIT_URL}")
echo("${env}")

node {
  git url: env.GIT_URL, branch: env.GIT_BRANCH
  sh "./build-support/bin/ci.sh"
}
