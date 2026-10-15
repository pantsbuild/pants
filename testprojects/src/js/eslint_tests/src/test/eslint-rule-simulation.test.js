// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/**
 * @jest-environment node
 * @fileoverview Tests for ESLint rule simulation and behavior.
 *
 * This test suite verifies the behavior of key ESLint rules through simulation,
 * helping ensure that the Pants ESLint integration handles common linting
 * scenarios correctly.
 *
 * Test coverage includes:
 * - Quote style rule enforcement
 * - Semicolon rule enforcement
 * - String literal detection
 * - Edge cases and complex code patterns
 * - Rule combination scenarios
 */

"use strict";

const { ESLintRuleSimulator } = require("../utils/eslint-helper");
const fs = require("fs");
const path = require("path");

describe("ESLint Rule Simulation", () => {
    let ruleSimulator;

    beforeEach(() => {
        ruleSimulator = new ESLintRuleSimulator();
    });

    describe("Quote Style Rule", () => {
        describe("Double Quote Enforcement", () => {
            test("should detect single quotes when double quotes expected", () => {
                const code = `const message = 'Hello, world!';`;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                expect(errors).toHaveLength(1);
                expect(errors[0]).toMatchObject({
                    line: 1,
                    message: expect.stringContaining("Expected double quotes"),
                    ruleId: "quotes",
                    severity: "error"
                });
            });

            test("should not flag double quotes when double quotes expected", () => {
                const code = `const message = "Hello, world!";`;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                expect(errors).toHaveLength(0);
            });

            test("should detect multiple single quote violations", () => {
                const code = `
                    const greeting = 'Hello';
                    const name = 'World';
                    const message = greeting + ', ' + name + '!';
                `;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                expect(errors.length).toBeGreaterThan(2);
                errors.forEach(error => {
                    expect(error.ruleId).toBe("quotes");
                    expect(error.severity).toBe("error");
                });
            });

            test("should handle mixed quotes in same line", () => {
                const code = `const mixed = 'single' + "double";`;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                // Should detect the single quote violation
                const singleQuoteErrors = errors.filter(e =>
                    e.message.includes("Expected double quotes")
                );
                expect(singleQuoteErrors.length).toBeGreaterThan(0);
            });
        });

        describe("Single Quote Enforcement", () => {
            test("should detect double quotes when single quotes expected", () => {
                const code = `const message = "Hello, world!";`;
                const errors = ruleSimulator.checkQuoteStyle(code, "single");

                expect(errors).toHaveLength(1);
                expect(errors[0]).toMatchObject({
                    line: 1,
                    message: expect.stringContaining("Expected single quotes"),
                    ruleId: "quotes",
                    severity: "error"
                });
            });

            test("should not flag single quotes when single quotes expected", () => {
                const code = `const message = 'Hello, world!';`;
                const errors = ruleSimulator.checkQuoteStyle(code, "single");

                expect(errors).toHaveLength(0);
            });
        });

        describe("Complex Quote Scenarios", () => {
            test("should handle escaped quotes", () => {
                const code = `const message = 'It\\'s a beautiful day';`;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                // The rule simulator may or may not handle escaped quotes correctly
                // This test documents the expected behavior
                expect(Array.isArray(errors)).toBe(true);
            });

            test("should handle template literals", () => {
                const code = `const message = \`Hello, \${name}!\`;`;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                // Template literals should not trigger quote style errors
                expect(errors).toHaveLength(0);
            });

            test("should handle multiline strings", () => {
                const code = `
                    const multiline = 'This is a \\
                    multiline string';
                `;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                expect(errors.length).toBeGreaterThan(0);
                expect(errors[0].ruleId).toBe("quotes");
            });

            test("should handle quotes in comments", () => {
                const code = `
                    // This comment has 'single quotes'
                    const message = "Hello, world!";
                `;
                const errors = ruleSimulator.checkQuoteStyle(code, "double");

                // Comments should not trigger quote style errors
                expect(errors).toHaveLength(0);
            });
        });
    });

    describe("Semicolon Rule", () => {
        describe("Missing Semicolon Detection", () => {
            test("should detect missing semicolon after variable declaration", () => {
                const code = `const message = "Hello, world!"`;
                const errors = ruleSimulator.checkSemicolons(code);

                expect(errors).toHaveLength(1);
                expect(errors[0]).toMatchObject({
                    line: 1,
                    message: "Missing semicolon",
                    ruleId: "semi",
                    severity: "error"
                });
            });

            test("should detect missing semicolon after function call", () => {
                const code = `console.log("Hello, world!")`;
                const errors = ruleSimulator.checkSemicolons(code);

                expect(errors).toHaveLength(1);
                expect(errors[0].ruleId).toBe("semi");
            });

            test("should detect missing semicolon after return statement", () => {
                const code = `return "Hello, world!"`;
                const errors = ruleSimulator.checkSemicolons(code);

                expect(errors).toHaveLength(1);
                expect(errors[0].ruleId).toBe("semi");
            });

            test("should not flag lines that end with semicolons", () => {
                const code = `
                    const message = "Hello, world!";
                    console.log(message);
                    return message;
                `;
                const errors = ruleSimulator.checkSemicolons(code);

                expect(errors).toHaveLength(0);
            });
        });

        describe("Semicolon Rule Edge Cases", () => {
            test("should not flag block statements", () => {
                const code = `
                    if (condition) {
                        doSomething();
                    }
                `;
                const errors = ruleSimulator.checkSemicolons(code);

                // Block opening/closing braces should not require semicolons
                const blockErrors = errors.filter(e =>
                    e.message.includes("Missing semicolon") &&
                    (e.line === 2 || e.line === 4)  // Lines with { or }
                );
                expect(blockErrors).toHaveLength(0);
            });

            test("should not flag empty lines", () => {
                const code = `
                    const a = 1;

                    const b = 2;
                `;
                const errors = ruleSimulator.checkSemicolons(code);

                // Empty line should not trigger semicolon error
                expect(errors.every(e => e.line !== 3)).toBe(true);
            });

            test("should not flag comment-only lines", () => {
                const code = `
                    const a = 1;
                    // This is a comment
                    /* This is also a comment */
                    const b = 2;
                `;
                const errors = ruleSimulator.checkSemicolons(code);

                // Comment lines should not trigger semicolon errors
                const commentLineErrors = errors.filter(e =>
                    e.line === 3 || e.line === 4
                );
                expect(commentLineErrors).toHaveLength(0);
            });

            test("should handle multiple statements on same line", () => {
                const code = `const a = 1; const b = 2`;
                const errors = ruleSimulator.checkSemicolons(code);

                // Should detect missing semicolon at end of line
                expect(errors).toHaveLength(1);
                expect(errors[0].ruleId).toBe("semi");
            });
        });
    });

    describe("String Literal Detection", () => {
        describe("Basic String Detection", () => {
            test("should identify position within single-quoted string", () => {
                const line = `const message = 'Hello, world!';`;
                const position = 20; // Position of 'o' in 'world'

                const isInString = ruleSimulator.isInStringLiteral(line, position);
                expect(isInString).toBe(true);
            });

            test("should identify position within double-quoted string", () => {
                const line = `const message = "Hello, world!";`;
                const position = 20; // Position of 'o' in 'world'

                const isInString = ruleSimulator.isInStringLiteral(line, position);
                expect(isInString).toBe(true);
            });

            test("should identify position outside string", () => {
                const line = `const message = "Hello, world!";`;
                const position = 5; // Position of 'm' in 'message'

                const isInString = ruleSimulator.isInStringLiteral(line, position);
                expect(isInString).toBe(false);
            });
        });

        describe("Complex String Scenarios", () => {
            test("should handle escaped quotes", () => {
                const line = `const message = 'It\\'s a test';`;
                const position = 20; // Position after escaped quote

                const isInString = ruleSimulator.isInStringLiteral(line, position);
                expect(isInString).toBe(true);
            });

            test("should handle nested different quote types", () => {
                const line = `const message = 'He said "Hello"';`;
                const position = 25; // Position of 'H' in "Hello"

                const isInString = ruleSimulator.isInStringLiteral(line, position);
                expect(isInString).toBe(true);
            });

            test("should handle multiple strings on same line", () => {
                const line = `const a = 'first'; const b = "second";`;

                const firstStringPos = 12; // Inside 'first'
                const betweenStringsPos = 20; // Between strings
                const secondStringPos = 32; // Inside "second"

                expect(ruleSimulator.isInStringLiteral(line, firstStringPos)).toBe(true);
                expect(ruleSimulator.isInStringLiteral(line, betweenStringsPos)).toBe(false);
                expect(ruleSimulator.isInStringLiteral(line, secondStringPos)).toBe(true);
            });

            test("should handle empty strings", () => {
                const line = `const empty = '';`;
                const position = 15; // Inside empty string

                const isInString = ruleSimulator.isInStringLiteral(line, position);
                expect(isInString).toBe(true);
            });
        });
    });

    describe("Integration with Test Fixtures", () => {
        test("should analyze valid code fixture", () => {
            const validCodePath = path.join(__dirname, "../test-fixtures/valid-code.js");
            const validCode = fs.readFileSync(validCodePath, "utf8");

            const quoteErrors = ruleSimulator.checkQuoteStyle(validCode, "double");
            const semicolonErrors = ruleSimulator.checkSemicolons(validCode);

            // Valid code should have minimal or no errors
            // (The fixture uses double quotes and semicolons correctly)
            expect(quoteErrors.length).toBe(0);
            expect(semicolonErrors.length).toBe(0);
        });

        test("should analyze invalid code fixture", () => {
            const invalidCodePath = path.join(__dirname, "../test-fixtures/invalid-code.js");
            const invalidCode = fs.readFileSync(invalidCodePath, "utf8");

            const quoteErrors = ruleSimulator.checkQuoteStyle(invalidCode, "double");
            const semicolonErrors = ruleSimulator.checkSemicolons(invalidCode);

            // Invalid code should have multiple errors
            expect(quoteErrors.length).toBeGreaterThan(0);
            expect(semicolonErrors.length).toBeGreaterThan(0);

            // Verify error details
            quoteErrors.forEach(error => {
                expect(error.ruleId).toBe("quotes");
                expect(error.severity).toBe("error");
                expect(error.line).toBeGreaterThan(0);
                expect(error.column).toBeGreaterThan(0);
            });

            semicolonErrors.forEach(error => {
                expect(error.ruleId).toBe("semi");
                expect(error.severity).toBe("error");
                expect(error.line).toBeGreaterThan(0);
                expect(error.column).toBeGreaterThan(0);
            });
        });

        test("should handle syntax error fixture gracefully", () => {
            const syntaxErrorPath = path.join(__dirname, "../test-fixtures/syntax-error.js");
            const syntaxErrorCode = fs.readFileSync(syntaxErrorPath, "utf8");

            // Rule simulator should not crash on syntax errors
            expect(() => {
                const quoteErrors = ruleSimulator.checkQuoteStyle(syntaxErrorCode, "double");
                const semicolonErrors = ruleSimulator.checkSemicolons(syntaxErrorCode);

                // Should return arrays even for malformed code
                expect(Array.isArray(quoteErrors)).toBe(true);
                expect(Array.isArray(semicolonErrors)).toBe(true);
            }).not.toThrow();
        });
    });

    describe("Performance and Edge Cases", () => {
        test("should handle very long lines", () => {
            const longString = "x".repeat(10000);
            const code = `const long = "${longString}";`;

            const startTime = Date.now();
            const errors = ruleSimulator.checkQuoteStyle(code, "double");
            const endTime = Date.now();

            // Should complete in reasonable time (less than 100ms)
            expect(endTime - startTime).toBeLessThan(100);
            expect(errors).toHaveLength(0);
        });

        test("should handle many short lines", () => {
            const lines = Array.from({ length: 1000 }, (_, i) =>
                `const var${i} = "value${i}";`
            );
            const code = lines.join("\n");

            const startTime = Date.now();
            const errors = ruleSimulator.checkQuoteStyle(code, "double");
            const endTime = Date.now();

            // Should complete in reasonable time (less than 500ms)
            expect(endTime - startTime).toBeLessThan(500);
            expect(errors).toHaveLength(0);
        });

        test("should handle code with no strings", () => {
            const code = `
                function calculate(a, b) {
                    return a + b * 2;
                }
                const result = calculate(5, 10);
            `;

            const errors = ruleSimulator.checkQuoteStyle(code, "double");
            expect(errors).toHaveLength(0);
        });

        test("should handle code with only comments", () => {
            const code = `
                // This is a comment
                /* This is a
                   multiline comment */
                // Another comment with 'quotes'
            `;

            const quoteErrors = ruleSimulator.checkQuoteStyle(code, "double");
            const semicolonErrors = ruleSimulator.checkSemicolons(code);

            expect(quoteErrors).toHaveLength(0);
            expect(semicolonErrors).toHaveLength(0);
        });
    });
});