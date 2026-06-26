{
  grpcServers: [{
    listenAddresses: [':8980'],
    authenticationPolicy: {allow: {}},
  }],
  schedulers: {
    '': {
      endpoint: {
        address: 'scheduler:8982',
        addMetadataJmespathExpression: {
          expression: |||
            {
              "build.bazel.remote.execution.v2.requestmetadata-bin": incomingGRPCMetadata."build.bazel.remote.execution.v2.requestmetadata-bin"
            }
          |||,
        },
      },
    },
  },
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {
    backend: {grpc: {client: {address: 'storage:8981'}}},
    getAuthorizer: {allow: {}},
    putAuthorizer: {allow: {}},
    findMissingAuthorizer: {allow: {}},
  },
  actionCache: {
    backend: {
      completenessChecking: {
        backend: {grpc: {client: {address: 'storage:8981'}}},
        maximumTotalTreeSizeBytes: 64 * 1024 * 1024,
      },
    },
    getAuthorizer: {allow: {}},
    putAuthorizer: {allow: {}},
  },
  fileSystemAccessCache: {
    backend: {grpc: {client: {address: 'storage:8981'}}},
    getAuthorizer: {allow: {}},
    putAuthorizer: {allow: {}},
  },
  executeAuthorizer: {allow: {}},
}
