// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
const parser = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const fs = require("fs").promises;

const printStringArguments = (callPath) => {
  for (const arg of callPath.node.arguments) {
    if (arg.type === "StringLiteral") {
      console.log(arg.value);
    }
  }
};

const functionImportsVisitor = {
  CallExpression: (callPath) => {
    callPath.traverse({
      Identifier: (identPath) => {
        if (identPath.node.name === "require") {
          printStringArguments(callPath);
        }
      },
      Import: () => printStringArguments(callPath),
    });
  },
};

const staticImportVisitor = {
  ImportDeclaration: (importPath) => {
    importPath.traverse({
      StringLiteral: (literalPath) => console.log(literalPath.node.value),
    });
  },
};

const main = async () => {
  const [file] = process.argv.slice(2);

  const code = await fs.readFile(file, "utf-8");

  const ast = parser.parse(code, {
    sourceType: "unambiguous",
    errorRecovery: true,
  });
  traverse(ast, {
    Program: (programPath) =>
      console.error(`Determined SourceType: ${programPath.node.sourceType}.`),
    ...functionImportsVisitor,
    ...staticImportVisitor,
  });
};

(async () => {
  try {
    await main();
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();
