if (!process.argv[2]) {
  console.log(`
Hello!

You can also run the following command to greet with name:

    yarn start -- name
    ./pants run.node contrib/node/examples/src/node/hello:pantsbuild-hello-node -- name
  `);
  process.exit(0);
}
console.log(`Hello, ${process.argv[2]}!`);
