echo("Test pipeline")
echo("${env.GIT_URL}")
echo("${env}")
echo(env.PATH)
echo(env.getEnvironment)

node {
  git url: 'https://github.com/pantsbuild/pants.git'
  sh "./build-support/bin/ci.sh"
}
