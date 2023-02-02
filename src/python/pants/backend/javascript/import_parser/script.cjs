const parser = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const fs = require("fs").promises;

const cjsRequireVisitor = {
  CallExpression(callPath) {
    callPath.traverse({
      Identifier(identPath) {
        if (identPath.node.name === "require") {
          for (const arg of callPath.node.arguments) {
            if (arg.type === "StringLiteral") {
              console.log(arg.value);
            }
          }
        }
      },
    });
  },
};

const mjsImportVisitor = {
  ImportDeclaration(importPath) {
    importPath.traverse({
      StringLiteral(literalPath) {
        console.log(literalPath.node.value);
      },
    });
  },
};

async function main() {
  const [file] = process.argv.slice(2);

  const code = await fs.readFile(file, "utf-8");

  const ast = parser.parse(code, {
    sourceType: "unambiguous",
    errorRecovery: true,
  });
  traverse(ast, {
    Program(programPath) {
      console.error(`Determined SourceType: ${programPath.node.sourceType}.`);
    },
    ...cjsRequireVisitor,
    ...mjsImportVisitor,
  });
}

(async () => {
  try {
    await main();
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();
