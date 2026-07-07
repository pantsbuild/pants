{
  blobstore: {
    contentAddressableStorage: {grpc: {client: {address: 'storage:8981'}}},
    actionCache: {
      completenessChecking: {
        backend: {grpc: {client: {address: 'storage:8981'}}},
        maximumTotalTreeSizeBytes: 64 * 1024 * 1024,
      },
    },
  },
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  scheduler: {address: 'scheduler:8983'},
  buildDirectories: [{
    native: {
      buildDirectoryPath: '/worker/build',
      cacheDirectoryPath: '/worker/cache',
      maximumCacheFileCount: 1000,
      maximumCacheSizeBytes: 512 * 1024 * 1024,
      cacheReplacementPolicy: 'LEAST_RECENTLY_USED',
    },
    runners: [{
      endpoint: {address: 'unix:///worker/runner'},
      concurrency: 1,
      instanceNamePrefix: '',
      workerId: {
        datacenter: 'pants',
        rack: 'buildbarn',
        slot: '1',
        hostname: 'pants-buildbarn-worker',
      },
    }],
  }],
  inputDownloadConcurrency: 4,
  outputUploadConcurrency: 4,
  directoryCache: {
    maximumCount: 1000,
    maximumSizeBytes: 1000 * 1024,
    cacheReplacementPolicy: 'LEAST_RECENTLY_USED',
  },
}
