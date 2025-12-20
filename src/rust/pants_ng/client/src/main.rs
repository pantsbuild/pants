// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use options_pants_ng::pants_invocation::Args;
use options_pants_ng::pants_invocation::PantsInvocation;

fn main() {
    // Currently this entry point does nothing except emit the parse of the args it was
    // invoked with. Useful for manual testing of the CLI, but eventually we'll put some
    // real functionality here.
    let invocation = PantsInvocation::from_args(Args::argv());
    println!("{:#?}", invocation.unwrap())
}
