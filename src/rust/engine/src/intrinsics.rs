use crate::context::{Context};
use futures::future::{self, Future};
use crate::core::{throw,/* Failure, Key, Params,*/ TypeId, Value};
use crate::nodes::{NodeFuture, Snapshot};
use crate::nodes::MultiPlatformExecuteProcess;
use crate::externs;
use boxfuture::Boxable;

pub fn run_intrinsic(input: TypeId, product: TypeId, context: Context, value: Value) -> NodeFuture<Value> {
  let types = &context.core.types;
  if product == types.process_result && input == types.multi_platform_process_request {
    multi_platform_process_request_to_process_result(context, value)
  } else {
    panic!("Unrecognized intrinsic: {:?} -> {:?}", input, product)
  }
}

fn multi_platform_process_request_to_process_result(context: Context, value: Value) -> NodeFuture<Value> {
  let core = context.core.clone();
  future::result(MultiPlatformExecuteProcess::lift(&value).map_err(|str| {
    throw(&format!(
        "Error lifting MultiPlatformExecuteProcess: {}",
        str
    ))
  })
  )
    .and_then(move |process_request| context.get(process_request))
    .map(move |result| {
      externs::unsafe_call(
        &core.types.construct_process_result,
        &[
        externs::store_bytes(&result.0.stdout),
        externs::store_bytes(&result.0.stderr),
        externs::store_i64(result.0.exit_code.into()),
        Snapshot::store_directory(&core, &result.0.output_directory),
        ],
      )
    })
  .to_boxed()
}
