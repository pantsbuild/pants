// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::fmt::Formatter;

use async_trait::async_trait;
use workunit_store::RunningWorkunit;

use crate::{CommandRunner, Context, FallibleProcessResultWithPlatform, Process, ProcessError};

pub struct SwitchedCommandRunner<F> {
  true_runner: Box<dyn CommandRunner>,
  false_runner: Box<dyn CommandRunner>,
  predicate: F,
}

impl<F> fmt::Debug for SwitchedCommandRunner<F> {
  fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
    f.debug_struct("SwitchedCommandRunner")
      .finish_non_exhaustive()
  }
}

impl<F> SwitchedCommandRunner<F>
where
  F: Fn(&Process) -> bool + Send + Sync,
{
  pub fn new(
    true_runner: Box<dyn CommandRunner>,
    false_runner: Box<dyn CommandRunner>,
    predicate: F,
  ) -> Self {
    Self {
      true_runner,
      false_runner,
      predicate,
    }
  }
}

#[async_trait]
impl<F> CommandRunner for SwitchedCommandRunner<F>
where
  F: Fn(&Process) -> bool + Send + Sync,
{
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    req: Process,
  ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
    if (self.predicate)(&req) {
      self.true_runner.run(context, workunit, req).await
    } else {
      self.false_runner.run(context, workunit, req).await
    }
  }
}

#[cfg(test)]
mod tests {
  use async_trait::async_trait;
  use workunit_store::{RunningWorkunit, WorkunitStore};

  use crate::switched::SwitchedCommandRunner;
  use crate::CommandRunner;
  use crate::{Context, FallibleProcessResultWithPlatform, Process, ProcessError};

  #[derive(Debug)]
  struct MockCommandRunner(Result<FallibleProcessResultWithPlatform, ProcessError>);

  #[async_trait]
  impl CommandRunner for MockCommandRunner {
    async fn run(
      &self,
      _context: Context,
      _workunit: &mut RunningWorkunit,
      _req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
      self.0.clone()
    }
  }

  #[tokio::test]
  async fn switched_command_runner() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let left = Box::new(MockCommandRunner(Err(ProcessError::Unclassified(
      "left".to_string(),
    ))));
    let right = Box::new(MockCommandRunner(Err(ProcessError::Unclassified(
      "right".to_string(),
    ))));

    let runner = SwitchedCommandRunner::new(left, right, |req| req.argv.get(0).unwrap() == "left");

    let req = Process::new(vec!["left".to_string()]);
    let err = runner
      .run(Context::default(), &mut workunit, req)
      .await
      .expect_err("expected error");
    if let ProcessError::Unclassified(msg) = &err {
      assert_eq!(msg, "left");
    } else {
      panic!("unexpected value: {:?}", err)
    }

    let req = Process::new(vec!["not-left".to_string()]);
    let err = runner
      .run(Context::default(), &mut workunit, req)
      .await
      .expect_err("expected error");
    if let ProcessError::Unclassified(msg) = &err {
      assert_eq!(msg, "right");
    } else {
      panic!("unexpected value: {:?}", err)
    }
  }
}
