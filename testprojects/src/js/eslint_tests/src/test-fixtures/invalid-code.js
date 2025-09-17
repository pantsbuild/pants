// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/**
 * Invalid JavaScript code that should fail ESLint checks.
 * This file is used as a test fixture for ESLint integration tests.
 *
 * Contains intentional ESLint violations:
 * - Wrong quote style (should be double quotes)
 * - Missing semicolons
 * - Unused variables
 * - Use of var instead of const/let
 * - Console.log statements
 */

'use strict'

// ESLint violation: wrong quotes, missing semicolon
var message = 'Hello, World!'

// ESLint violation: unused variable
var unused = 'This variable is not used'

// ESLint violation: var instead of const/let
var counter = 0

// ESLint violation: console.log, missing semicolon
console.log('Starting application')

function greetUser(name) {
    // ESLint violation: wrong quotes, missing semicolon
    var greeting = 'Hello, ' + name + '!'

    // ESLint violation: console.log, missing semicolon
    console.log(greeting)

    // ESLint violation: missing semicolon
    return greeting
}

// ESLint violation: wrong quotes, missing semicolon
var users = ['Alice', 'Bob', 'Charlie']

// ESLint violation: var instead of const
for (var i = 0; i < users.length; i++) {
    // ESLint violation: wrong quotes, missing semicolon
    greetUser(users[i])
}

// ESLint violation: unused function
function unusedFunction() {
    // ESLint violation: wrong quotes, missing semicolon
    return 'This function is never called'
}

// ESLint violation: missing semicolon
var config = {
    // ESLint violation: wrong quotes
    apiUrl: 'https://api.example.com',
    // ESLint violation: wrong quotes
    version: '1.0.0'
}

// ESLint violation: console.log, wrong quotes, missing semicolon
console.log('Configuration loaded:', config)