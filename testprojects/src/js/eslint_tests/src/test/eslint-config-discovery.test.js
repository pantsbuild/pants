// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/**
 * @jest-environment node
 * @fileoverview Tests for ESLint configuration discovery functionality.
 *
 * This test suite verifies that the ESLint integration correctly discovers
 * and uses configuration files according to ESLint's documented behavior.
 *
 * Test coverage includes:
 * - Flat config file discovery (eslint.config.js, etc.)
 * - Legacy config file discovery (.eslintrc, .eslintrc.json, etc.)
 * - Package.json eslintConfig discovery
 * - Config file precedence and resolution order
 * - Edge cases and error handling
 */

"use strict";

const { ESLintConfigHelper, FileTestUtils } = require("../utils/eslint-helper");
const path = require("path");

describe("ESLint Configuration Discovery", () => {
    let tempDir;
    let configHelper;

    beforeEach(() => {
        // Create a fresh temporary directory for each test
        tempDir = FileTestUtils.createTempDirectory({});
        configHelper = new ESLintConfigHelper(tempDir);
    });

    afterEach(() => {
        // Clean up temporary directory
        if (tempDir) {
            FileTestUtils.cleanupTempDirectory(tempDir);
        }
    });

    describe("Config File Discovery Order", () => {
        test("should return correct discovery order", () => {
            const order = configHelper.getConfigDiscoveryOrder();

            expect(order).toEqual([
                "eslint.config.js",
                "eslint.config.mjs",
                "eslint.config.cjs",
                ".eslintrc",
                ".eslintrc.js",
                ".eslintrc.cjs",
                ".eslintrc.yaml",
                ".eslintrc.yml",
                ".eslintrc.json",
                "package.json"
            ]);
        });

        test("should prioritize flat config files over legacy config files", () => {
            const order = configHelper.getConfigDiscoveryOrder();
            const flatConfigs = ["eslint.config.js", "eslint.config.mjs", "eslint.config.cjs"];
            const legacyConfigs = [".eslintrc", ".eslintrc.js", ".eslintrc.json"];

            flatConfigs.forEach(flatConfig => {
                legacyConfigs.forEach(legacyConfig => {
                    const flatIndex = order.indexOf(flatConfig);
                    const legacyIndex = order.indexOf(legacyConfig);
                    expect(flatIndex).toBeLessThan(legacyIndex);
                });
            });
        });
    });

    describe("Flat Config Discovery", () => {
        test("should discover eslint.config.js", () => {
            const configContent = `export default {
                rules: {
                    "quotes": ["error", "double"]
                }
            };`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.js": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain("eslint.config.js");
        });

        test("should discover eslint.config.mjs", () => {
            const configContent = `export default {
                rules: {
                    "semi": ["error", "always"]
                }
            };`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.mjs": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain("eslint.config.mjs");
        });

        test("should discover eslint.config.cjs", () => {
            const configContent = `module.exports = {
                rules: {
                    "no-unused-vars": "error"
                }
            };`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.cjs": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain("eslint.config.cjs");
        });

        test("should prefer eslint.config.js over other flat configs", () => {
            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.js": "export default {};",
                "eslint.config.mjs": "export default {};",
                "eslint.config.cjs": "module.exports = {};"
            });

            const effectiveConfig = configHelper.getEffectiveConfig();
            expect(effectiveConfig).toBe("eslint.config.js");
        });
    });

    describe("Legacy Config Discovery", () => {
        test("should discover .eslintrc", () => {
            const configContent = `{
                "rules": {
                    "quotes": ["error", "double"]
                }
            }`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain(".eslintrc");
        });

        test("should discover .eslintrc.json", () => {
            const configContent = `{
                "rules": {
                    "semi": ["error", "always"]
                }
            }`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.json": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain(".eslintrc.json");
        });

        test("should discover .eslintrc.js", () => {
            const configContent = `module.exports = {
                rules: {
                    "no-unused-vars": "error"
                }
            };`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.js": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain(".eslintrc.js");
        });

        test("should discover .eslintrc.yaml", () => {
            const configContent = `rules:
  quotes:
    - error
    - double`;

            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.yaml": configContent
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain(".eslintrc.yaml");
        });

        test("should prefer .eslintrc over other legacy formats", () => {
            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc": "{}",
                ".eslintrc.json": "{}",
                ".eslintrc.js": "module.exports = {};"
            });

            const effectiveConfig = configHelper.getEffectiveConfig();
            expect(effectiveConfig).toBe(".eslintrc");
        });
    });

    describe("Package.json Config Discovery", () => {
        test("should discover eslintConfig in package.json", () => {
            const packageJson = {
                name: "test-project",
                eslintConfig: {
                    rules: {
                        "quotes": ["error", "double"]
                    }
                }
            };

            FileTestUtils.createDirectoryStructure(tempDir, {
                "package.json": JSON.stringify(packageJson, null, 2)
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain("package.json");
        });

        test("should not discover package.json without eslintConfig", () => {
            const packageJson = {
                name: "test-project",
                scripts: {
                    test: "jest"
                }
            };

            FileTestUtils.createDirectoryStructure(tempDir, {
                "package.json": JSON.stringify(packageJson, null, 2)
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).not.toContain("package.json");
        });

        test("should handle malformed package.json gracefully", () => {
            FileTestUtils.createDirectoryStructure(tempDir, {
                "package.json": "{ invalid json content"
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).not.toContain("package.json");
        });
    });

    describe("Config Precedence", () => {
        test("should prefer flat config over legacy config", () => {
            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.js": "export default {};",
                ".eslintrc.json": "{}"
            });

            const effectiveConfig = configHelper.getEffectiveConfig();
            expect(effectiveConfig).toBe("eslint.config.js");
        });

        test("should prefer legacy config over package.json", () => {
            const packageJson = {
                name: "test-project",
                eslintConfig: { rules: {} }
            };

            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.json": "{}",
                "package.json": JSON.stringify(packageJson, null, 2)
            });

            const effectiveConfig = configHelper.getEffectiveConfig();
            expect(effectiveConfig).toBe(".eslintrc.json");
        });

        test("should use package.json when no other configs exist", () => {
            const packageJson = {
                name: "test-project",
                eslintConfig: { rules: {} }
            };

            FileTestUtils.createDirectoryStructure(tempDir, {
                "package.json": JSON.stringify(packageJson, null, 2)
            });

            const effectiveConfig = configHelper.getEffectiveConfig();
            expect(effectiveConfig).toBe("package.json");
        });
    });

    describe("Edge Cases", () => {
        test("should handle empty directory", () => {
            const existing = configHelper.findExistingConfigs();
            expect(existing).toEqual([]);

            const effectiveConfig = configHelper.getEffectiveConfig();
            expect(effectiveConfig).toBeNull();
        });

        test("should handle directory with unrelated files", () => {
            FileTestUtils.createDirectoryStructure(tempDir, {
                "index.js": "console.log('hello');",
                "README.md": "# Test Project",
                "styles.css": "body { margin: 0; }"
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toEqual([]);
        });

        test("should handle multiple configs and return all existing", () => {
            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.js": "export default {};",
                ".eslintrc.json": "{}",
                ".eslintrc.js": "module.exports = {};"
            });

            const existing = configHelper.findExistingConfigs();
            expect(existing).toContain("eslint.config.js");
            expect(existing).toContain(".eslintrc.json");
            expect(existing).toContain(".eslintrc.js");
            expect(existing.length).toBe(3);
        });

        test("should handle permission errors gracefully", () => {
            // This test would require platform-specific permission manipulation
            // For now, we test that the method doesn't throw on file access errors
            expect(() => {
                configHelper.findExistingConfigs("/nonexistent/directory");
            }).not.toThrow();
        });
    });

    describe("Config Validation", () => {
        test("should validate valid JSON config", () => {
            const configPath = path.join(tempDir, ".eslintrc.json");
            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.json": `{
                    "rules": {
                        "quotes": ["error", "double"]
                    }
                }`
            });

            const isValid = configHelper.validateConfigFile(configPath);
            expect(isValid).toBe(true);
        });

        test("should reject invalid JSON config", () => {
            const configPath = path.join(tempDir, ".eslintrc.json");
            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.json": "{ invalid json"
            });

            const isValid = configHelper.validateConfigFile(configPath);
            expect(isValid).toBe(false);
        });

        test("should validate JS config files", () => {
            const configPath = path.join(tempDir, "eslint.config.js");
            FileTestUtils.createDirectoryStructure(tempDir, {
                "eslint.config.js": "export default { rules: {} };"
            });

            const isValid = configHelper.validateConfigFile(configPath);
            expect(isValid).toBe(true);
        });

        test("should reject empty config files", () => {
            const configPath = path.join(tempDir, ".eslintrc.json");
            FileTestUtils.createDirectoryStructure(tempDir, {
                ".eslintrc.json": ""
            });

            const isValid = configHelper.validateConfigFile(configPath);
            expect(isValid).toBe(false);
        });

        test("should handle nonexistent config files", () => {
            const configPath = path.join(tempDir, "nonexistent.json");

            const isValid = configHelper.validateConfigFile(configPath);
            expect(isValid).toBe(false);
        });
    });
});