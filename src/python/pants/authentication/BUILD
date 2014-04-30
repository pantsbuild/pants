from pants.authentication.netrc_util import Netrc

netrc = Netrc()

credentials(
  name = 'netrc',
  username=netrc.getusername,
  password=netrc.getpassword)

python_library(
  name = 'authentication',
  sources = globs('*.py'),
)
