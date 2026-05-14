// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
import assert from "assert";

import { add } from "../index.mjs";

it("adds 1 + 2 to equal 3", () => {
  assert.equal(add(1, 2), 3);
});
