// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/**
 * Utility functions for testing ESLint integration.
 * These utilities help simulate and test ESLint behavior.
 */

"use strict";

const fs = require("fs");
const path = require("path");

/**
 * Simulates ESLint configuration discovery behavior.
 * This helps test the configuration file resolution logic.
 */
class ESLintConfigHelper {
    /**
     * Creates a new ESLint configuration helper.
     * @param {string} baseDir - Base directory for config discovery
     */
    constructor(baseDir = process.cwd()) {
        this.baseDir = baseDir;
    }

    /**
     * Gets the expected config file discovery order as per ESLint docs.
     * @returns {string[]} Array of config file names in discovery order
     */
    getConfigDiscoveryOrder() {
        return [
            // Flat config files (ESLint 9.0+)
            "eslint.config.js",
            "eslint.config.mjs",
            "eslint.config.cjs",
            // Legacy config files
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.cjs",
            ".eslintrc.yaml",
            ".eslintrc.yml",
            ".eslintrc.json",
            // Package.json with eslintConfig
            "package.json"
        ];
    }

    /**
     * Checks which config files exist in the given directory.
     * @param {string} dir - Directory to check
     * @returns {string[]} Array of existing config files
     */
    findExistingConfigs(dir = this.baseDir) {
        const configFiles = this.getConfigDiscoveryOrder();
        const existing = [];

        for (const configFile of configFiles) {
            const configPath = path.join(dir, configFile);
            try {
                if (fs.existsSync(configPath)) {
                    if (configFile === "package.json") {
                        // Check if package.json contains eslintConfig
                        const packageJson = JSON.parse(fs.readFileSync(configPath, "utf8"));
                        if (packageJson.eslintConfig) {
                            existing.push(configFile);
                        }
                    } else {
                        existing.push(configFile);
                    }
                }
            } catch (error) {
                // Ignore errors for individual files
                continue;
            }
        }

        return existing;
    }

    /**
     * Simulates the config file that ESLint would use.
     * @param {string} dir - Directory to check
     * @returns {string|null} The config file that would be used, or null
     */
    getEffectiveConfig(dir = this.baseDir) {
        const existing = this.findExistingConfigs(dir);
        return existing.length > 0 ? existing[0] : null;
    }

    /**
     * Validates that a config file has valid JSON/JS syntax.
     * @param {string} configPath - Path to config file
     * @returns {boolean} True if config file is valid
     */
    validateConfigFile(configPath) {
        try {
            const content = fs.readFileSync(configPath, "utf8");
            const ext = path.extname(configPath);

            if (ext === ".json" || path.basename(configPath) === ".eslintrc") {
                JSON.parse(content);
                return true;
            } else if (ext === ".js" || ext === ".mjs" || ext === ".cjs") {
                // For JS files, we can't easily validate without executing
                // In a real scenario, this would require more sophisticated parsing
                return content.trim().length > 0;
            } else if (ext === ".yaml" || ext === ".yml") {
                // Would require yaml parser in real implementation
                return content.trim().length > 0;
            }

            return false;
        } catch (error) {
            return false;
        }
    }
}

/**
 * Simulates ESLint rule execution for testing.
 * This helps test rule application without running actual ESLint.
 */
class ESLintRuleSimulator {
    /**
     * Simulates quote style rule checking.
     * @param {string} code - JavaScript code to check
     * @param {string} expectedQuoteStyle - Expected quote style ("single" or "double")
     * @returns {Object[]} Array of simulated lint errors
     */
    checkQuoteStyle(code, expectedQuoteStyle = "double") {
        const errors = [];
        const lines = code.split("\n");

        lines.forEach((line, index) => {
            // Skip comment lines
            const trimmed = line.trim();
            if (trimmed.startsWith("//") || trimmed.startsWith("/*") || trimmed.startsWith("*")) {
                return;
            }

            // Remove comments from the line for processing
            let processLine = line;
            const commentIndex = line.indexOf("//");
            if (commentIndex !== -1) {
                processLine = line.substring(0, commentIndex);
            }

            const wrongQuoteRegex = expectedQuoteStyle === "double"
                ? /'/g  // Find single quotes when double expected
                : /"/g; // Find double quotes when single expected

            let match;
            wrongQuoteRegex.lastIndex = 0; // Reset regex
            while ((match = wrongQuoteRegex.exec(processLine)) !== null) {
                // Check if this quote is actually starting/ending a string literal
                if (this.isQuoteStartingString(processLine, match.index)) {
                    errors.push({
                        line: index + 1,
                        column: match.index + 1,
                        message: `Expected ${expectedQuoteStyle} quotes but found ${expectedQuoteStyle === "double" ? "single" : "double"} quotes`,
                        ruleId: "quotes",
                        severity: "error"
                    });
                }
            }
        });

        return errors;
    }

    /**
     * Simulates semicolon rule checking.
     * @param {string} code - JavaScript code to check
     * @returns {Object[]} Array of simulated lint errors
     */
    checkSemicolons(code) {
        const errors = [];
        const lines = code.split("\n");

        lines.forEach((line, index) => {
            const trimmed = line.trim();

            // Skip empty lines, comments, and JSDoc
            if (trimmed.length === 0 ||
                trimmed.startsWith("//") ||
                trimmed.startsWith("/*") ||
                trimmed.startsWith("*") ||
                trimmed.endsWith("*/") ||
                trimmed.startsWith("/**")) {
                return;
            }

            // Skip lines that don't need semicolons
            if (trimmed.endsWith("{") ||
                trimmed.endsWith("}") ||
                trimmed.endsWith(";") ||
                trimmed.endsWith("||") ||
                trimmed.endsWith("&&") ||
                trimmed.endsWith(",") ||
                trimmed.startsWith("function ") ||
                trimmed.startsWith("if ") ||
                trimmed.startsWith("else") ||
                trimmed.startsWith("for ") ||
                trimmed.startsWith("while ") ||
                trimmed.startsWith("try ") ||
                trimmed.startsWith("catch ") ||
                trimmed.startsWith("finally ") ||
                trimmed.match(/^(const|let|var)\s+\w+\s*=\s*function/) ||
                trimmed.match(/^\w+\s*\(/)) { // Function calls without assignment
                return;
            }

            // Check for statements that need semicolons
            if (trimmed.match(/^(const|let|var)\s+/) ||
                trimmed.match(/^return\s+/) ||
                trimmed.match(/^throw\s+/) ||
                trimmed.match(/^\w+\s*=/) ||
                trimmed.match(/^\w+\.\w+/) ||
                trimmed.match(/^.*\)\s*$/) && !trimmed.includes("function")) {

                errors.push({
                    line: index + 1,
                    column: trimmed.length + 1,
                    message: "Missing semicolon",
                    ruleId: "semi",
                    severity: "error"
                });
            }
        });

        return errors;
    }

    /**
     * Helper method to check if a quote at a position is starting a string literal.
     * @param {string} line - Line of code
     * @param {number} position - Character position of the quote
     * @returns {boolean} True if position is starting a string literal
     */
    isQuoteStartingString(line, position) {
        const quoteChar = line[position];
        let inString = false;
        let stringChar = null;
        let escaped = false;

        for (let i = 0; i < line.length; i++) {
            const char = line[i];

            if (escaped) {
                escaped = false;
                continue;
            }

            if (char === "\\") {
                escaped = true;
                continue;
            }

            if (!inString && (char === "'" || char === '"')) {
                if (i === position) {
                    return true; // This is the start of a string
                }
                inString = true;
                stringChar = char;
            } else if (inString && char === stringChar) {
                if (i === position) {
                    return false; // This is the end of a string
                }
                inString = false;
                stringChar = null;
            } else if (i === position && inString) {
                return false; // This quote is inside a string, not starting it
            }
        }

        return false;
    }

    /**
     * Helper method to check if a character position is within a string literal.
     * @param {string} line - Line of code
     * @param {number} position - Character position
     * @returns {boolean} True if position is in a string literal
     */
    isInStringLiteral(line, position) {
        // Simplified check - real implementation would be much more complex
        let inSingleQuote = false;
        let inDoubleQuote = false;
        let escaped = false;

        for (let i = 0; i < position; i++) {
            const char = line[i];

            if (escaped) {
                escaped = false;
                continue;
            }

            if (char === "\\") {
                escaped = true;
                continue;
            }

            if (char === "'" && !inDoubleQuote) {
                inSingleQuote = !inSingleQuote;
            } else if (char === "\"" && !inSingleQuote) {
                inDoubleQuote = !inDoubleQuote;
            }
        }

        return inSingleQuote || inDoubleQuote;
    }
}

/**
 * Test utilities for file operations.
 */
class FileTestUtils {
    /**
     * Creates a temporary file with given content.
     * @param {string} content - File content
     * @param {string} extension - File extension (default: .js)
     * @returns {string} Path to temporary file
     */
    static createTempFile(content, extension = ".js") {
        const tmpDir = require("os").tmpdir();
        const fileName = `test-${Date.now()}-${Math.random().toString(36).substr(2, 9)}${extension}`;
        const filePath = path.join(tmpDir, fileName);

        fs.writeFileSync(filePath, content, "utf8");
        return filePath;
    }

    /**
     * Cleans up a temporary file.
     * @param {string} filePath - Path to file to delete
     */
    static cleanupTempFile(filePath) {
        try {
            if (fs.existsSync(filePath)) {
                fs.unlinkSync(filePath);
            }
        } catch (error) {
            // Ignore cleanup errors
        }
    }

    /**
     * Creates a temporary directory structure for testing.
     * @param {Object} structure - Directory structure object
     * @returns {string} Path to temporary directory
     */
    static createTempDirectory(structure) {
        const tmpDir = require("os").tmpdir();
        const dirName = `test-dir-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        const dirPath = path.join(tmpDir, dirName);

        fs.mkdirSync(dirPath, { recursive: true });

        this.createDirectoryStructure(dirPath, structure);

        return dirPath;
    }

    /**
     * Recursively creates directory structure.
     * @param {string} basePath - Base directory path
     * @param {Object} structure - Structure object
     */
    static createDirectoryStructure(basePath, structure) {
        for (const [name, content] of Object.entries(structure)) {
            const itemPath = path.join(basePath, name);

            if (typeof content === "string") {
                // File
                fs.writeFileSync(itemPath, content, "utf8");
            } else if (typeof content === "object" && content !== null) {
                // Directory
                fs.mkdirSync(itemPath, { recursive: true });
                this.createDirectoryStructure(itemPath, content);
            }
        }
    }

    /**
     * Recursively removes a directory and all its contents.
     * @param {string} dirPath - Directory path to remove
     */
    static cleanupTempDirectory(dirPath) {
        try {
            if (fs.existsSync(dirPath)) {
                fs.rmSync(dirPath, { recursive: true, force: true });
            }
        } catch (error) {
            // Ignore cleanup errors
        }
    }
}

module.exports = {
    ESLintConfigHelper,
    ESLintRuleSimulator,
    FileTestUtils
};