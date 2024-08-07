// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
const assert = require("node:assert");

const { add } = require("../index.cjs");

it("adds 1 + 2 to equal 3", () => {
  assert.equal(add(1, 2), 3);
});
