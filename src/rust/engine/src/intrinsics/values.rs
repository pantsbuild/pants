// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use futures::future::{BoxFuture, FutureExt};

use crate::context::Context;
use crate::nodes::{NodeResult, RunId, SessionValues};
use crate::python::Value;

pub(crate) fn session_values(
    context: Context,
    _args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move { context.get(SessionValues).await }.boxed()
}

pub(crate) fn run_id(context: Context, _args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
    async move { context.get(RunId).await }.boxed()
}
