// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
/**
 * @jest-environment node
 */

import { expect } from "@jest/globals";

import { add } from "../index.mjs";

test("adds 1 + 2 to equal 3", () => {
  expect(add(1, 2)).toBe(3);
});
