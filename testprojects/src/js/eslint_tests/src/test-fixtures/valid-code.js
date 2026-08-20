// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/**
 * Valid JavaScript code that should pass ESLint checks.
 * This file is used as a test fixture for ESLint integration tests.
 */

"use strict";

/**
 * Greets a person with a customizable message.
 * @param {string} name - The name of the person to greet
 * @param {string} greeting - Optional greeting message
 * @returns {string} The complete greeting message
 */
function greetPerson(name, greeting = "Hello") {
    if (!name || typeof name !== "string") {
        throw new Error("Name must be a non-empty string");
    }

    const message = `${greeting}, ${name}!`;
    return message;
}

/**
 * Calculates the sum of numbers in an array.
 * @param {number[]} numbers - Array of numbers to sum
 * @returns {number} The sum of all numbers
 */
function calculateSum(numbers) {
    if (!Array.isArray(numbers)) {
        throw new Error("Input must be an array");
    }

    return numbers.reduce((sum, num) => {
        if (typeof num !== "number") {
            throw new Error("All array elements must be numbers");
        }
        return sum + num;
    }, 0);
}

/**
 * Utility object with various helper functions.
 */
const utils = {
    /**
     * Checks if a value is empty (null, undefined, empty string, or empty array).
     * @param {*} value - The value to check
     * @returns {boolean} True if the value is considered empty
     */
    isEmpty(value) {
        return value === null ||
               value === undefined ||
               value === "" ||
               (Array.isArray(value) && value.length === 0);
    },

    /**
     * Capitalizes the first letter of a string.
     * @param {string} str - The string to capitalize
     * @returns {string} The capitalized string
     */
    capitalize(str) {
        if (typeof str !== "string") {
            return str;
        }
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
};

// Export functions for testing
if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        greetPerson,
        calculateSum,
        utils
    };
}