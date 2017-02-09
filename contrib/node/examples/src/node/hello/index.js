if(!process.argv[2]){
  console.log(`
Hello!

You can also run one of the following command to greet with name:

    npm run start -- name
    yarn run start -- name
    ./pants run contrib/node/examples/src/node/hello:pantsbuild-hello-node -- name
  `)
  process.exit(0)
}
console.log(`Hello, ${process.argv[2]}!`)
