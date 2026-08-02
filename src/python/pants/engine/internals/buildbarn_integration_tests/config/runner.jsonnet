{
  buildDirectoryPath: '/worker/build',
  grpcServers: [{
    listenPaths: ['/worker/runner'],
    authenticationPolicy: {allow: {}},
  }],
}
