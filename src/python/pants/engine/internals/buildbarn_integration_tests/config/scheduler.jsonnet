{
  clientGrpcServers: [{
    listenAddresses: [':8982'],
    authenticationPolicy: {allow: {}},
  }],
  workerGrpcServers: [{
    listenAddresses: [':8983'],
    authenticationPolicy: {allow: {}},
  }],
  buildQueueStateGrpcServers: [{
    listenAddresses: [':8984'],
    authenticationPolicy: {allow: {}},
  }],
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {grpc: {client: {address: 'storage:8981'}}},
  executeAuthorizer: {allow: {}},
  modifyDrainsAuthorizer: {allow: {}},
  killOperationsAuthorizer: {allow: {}},
  synchronizeAuthorizer: {allow: {}},
  actionRouter: {
    simple: {
      platformKeyExtractor: {action: {}},
      invocationKeyExtractors: [{correlatedInvocationsId: {}}, {toolInvocationId: {}}],
      initialSizeClassAnalyzer: {
        defaultExecutionTimeout: '1800s',
        maximumExecutionTimeout: '7200s',
      },
    },
  },
  platformQueueWithNoWorkersTimeout: '900s',
}
