golang_rev = '1.9.2'

rpm_package(
  name='golang',
  spec='golang.spec',
  remote_sources=[
    'https://storage.googleapis.com/golang/go{}.linux-amd64.tar.gz'.format(golang_rev),
  ],
  defines={
    'version': golang_rev,
  },
)
