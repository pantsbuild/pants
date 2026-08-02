{
  grpcServers: [{
    listenAddresses: [':8981'],
    authenticationPolicy: {allow: {}},
  }],
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {
    backend: {
      'local': {
        keyLocationMapOnBlockDevice: {file: {path: '/storage-cas/key_location_map', sizeBytes: 16 * 1024 * 1024}},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 3,
        blocksOnBlockDevice: {source: {file: {path: '/storage-cas/blocks', sizeBytes: 1024 * 1024 * 1024}}, spareBlocks: 3},
        persistent: {stateDirectoryPath: '/storage-cas/persistent_state', minimumEpochInterval: '300s'},
      },
    },
    getAuthorizer: {allow: {}},
    putAuthorizer: {allow: {}},
    findMissingAuthorizer: {allow: {}},
  },
  actionCache: {
    backend: {
      'local': {
        keyLocationMapOnBlockDevice: {file: {path: '/storage-ac/key_location_map', sizeBytes: 1024 * 1024}},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 1,
        blocksOnBlockDevice: {source: {file: {path: '/storage-ac/blocks', sizeBytes: 128 * 1024 * 1024}}, spareBlocks: 3},
        persistent: {stateDirectoryPath: '/storage-ac/persistent_state', minimumEpochInterval: '300s'},
      },
    },
    getAuthorizer: {allow: {}},
    putAuthorizer: {allow: {}},
  },
  fileSystemAccessCache: {
    backend: {
      'local': {
        keyLocationMapOnBlockDevice: {file: {path: '/storage-fsac/key_location_map', sizeBytes: 1024 * 1024}},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 1,
        blocksOnBlockDevice: {source: {file: {path: '/storage-fsac/blocks', sizeBytes: 128 * 1024 * 1024}}, spareBlocks: 3},
        persistent: {stateDirectoryPath: '/storage-fsac/persistent_state', minimumEpochInterval: '300s'},
      },
    },
    getAuthorizer: {allow: {}},
    putAuthorizer: {allow: {}},
  },
}
