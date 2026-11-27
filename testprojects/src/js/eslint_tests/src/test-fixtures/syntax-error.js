// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/**
 * JavaScript code with syntax errors.
 * This file is used as a test fixture for ESLint integration tests
 * to ensure proper handling of syntax errors.
 */

"use strict";

// Syntax error: unclosed function
function brokenFunction(param1, param2 {
    return param1 + param2;
}

// Syntax error: unmatched bracket
const array = [1, 2, 3;

// Syntax error: unclosed string literal
const message = "This string is not closed

// Syntax error: invalid object literal
const config = {
    key1: "value1",
    key2: "value2"
    key3: "value3"  // Missing comma
};

// Syntax error: mismatched parentheses
if (condition && (other || third) {
    console.log("This will not parse");
}