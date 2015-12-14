var http = require('http');

class Server {
  constructor(address, port) {
    this.address = address;
    this.port = port;
  }

  start(message) {
    http.createServer(function(request, response) {
      response.writeHead(200, {'Content-Type': 'text/plain'});
      response.end(message);
    }).listen(this.port, this.address);
  }
}

module.exports = Server;
