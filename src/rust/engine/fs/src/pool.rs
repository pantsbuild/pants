// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::RwLock;

use futures::future::IntoFuture;
use futures_cpupool::{self, CpuFuture, CpuPool};

///
/// A wrapper around a CpuPool, to add the ability to drop the pool before forking,
/// and then lazily re-initialize it in a new process.
///
/// When a process forks, the kernel clones only the thread that called fork: all other
/// threads are effectively destroyed. If a CpuPool has live threads during a fork, it
/// will not be able to perform any work or be dropped cleanly (it will hang instead).
/// It's thus necessary to drop the pool before forking, and to re-create it after forking.
///
pub struct ResettablePool {
  name_prefix: String,
  pool: RwLock<Option<CpuPool>>,
}

impl ResettablePool {
  pub fn new(name_prefix: String) -> ResettablePool {
    ResettablePool {
      name_prefix: name_prefix,
      pool: RwLock::new(None),
    }
  }

  ///
  /// Delegates to `CpuPool::spawn_fn`, and shares its signature.
  /// http://alexcrichton.com/futures-rs/futures_cpupool/struct.CpuPool.html#method.spawn_fn
  ///
  pub fn spawn_fn<F, R>(&self, f: F) -> CpuFuture<R::Item, R::Error>
  where
    F: FnOnce() -> R + Send + 'static,
    R: IntoFuture + 'static,
    R::Future: Send + 'static,
    R::Item: Send + 'static,
    R::Error: Send + 'static,
  {
    {
      // The happy path: pool is already initialized.
      let pool_opt = self.pool.read().unwrap();
      if let Some(ref pool) = *pool_opt {
        return pool.spawn_fn(f);
      }
    }
    {
      // Initialize the pool, but then release the write lock.
      let mut pool_opt = self.pool.write().unwrap();
      pool_opt.get_or_insert_with(|| self.new_pool());
    }

    // Recurse to run the function under the read lock.
    self.spawn_fn(f)
  }

  pub fn reset(&self) {
    let mut pool = self.pool.write().unwrap();
    *pool = None;
  }

  fn new_pool(&self) -> CpuPool {
    futures_cpupool::Builder::new()
      .name_prefix(self.name_prefix.clone())
      .create()
  }
}
