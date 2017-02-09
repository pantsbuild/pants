if(!process.argv[2]){
  console.log(`
Hello!

You can run mocha test with one of the following command:

    npm run test
    yarn run test
    ./pants test contrib/node/examples/src/node/hello-test:pantsbuild-hello-mocha
  `)
  process.exit(0)
}
console.log(`Hello, ${process.argv[2]}!`)
