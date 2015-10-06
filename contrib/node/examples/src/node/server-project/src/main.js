#! /usr/bin/env node

var Server = require("./Server");

new Server('127.0.0.1', 8080).start('Hello world');
console.log('Server started...');
