---
title: "Explorer APIs (advanced)"
slug: "rules-api-explorer"
excerpt: "Pants HTTP APIs."
hidden: false
createdAt: "2022-11-20T18:00:00Z"
updatedAt: "2022-11-20T18:00:00Z"
---
> 📘 The experimental status of the explorer backend merely means that there may be incompatible
> changes without respecting our deprecation policy.

The "Explorer Web UI" is a collection of backend APIs to provide a rich graphical frontend user interace. Provided with Pants core features are the infrastructure to run the backend server and a few default APIs. Any additional functionality is then registered by plugins.

Enable the backend `pants.backend.explorer` to get the default explorer server implementation with a [`uvicorn`](https://www.uvicorn.org/) API server and a [`strawberry`](https://strawberry.rocks/) based GraphQL API.

The GraphQL API offer the data available in the Pants engine and its plugins to any GraphQL compatible client over a local HTTP connection (incomplete, WIP). The core engine have a builtin schema and plugins may extend this with custom types and queries etc.

The local server is started with:

```
❯ ./pants experimental-explorer --graphql-open-graphiql
14:07:29.22 [INFO] Using UvicornServerRequest to create the explorer server.
14:07:29.32 [INFO] Starting the Explorer Web UI server...
14:07:29.42 [INFO] Completed: Open http://localhost:8000/graphql with default web browser.
14:07:29.42 [INFO] Started server process [32128]
14:07:29.42 [INFO] Waiting for application startup.
14:07:29.42 [INFO] Application startup complete.
14:07:29.42 [INFO] Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
14:07:29.48 [INFO] ::1:55865 - "GET /graphql HTTP/1.1" 200
14:07:31.69 [INFO] ('::1', 55869) - "WebSocket /graphql" [accepted]
14:07:31.69 [INFO] connection open
14:07:31.76 [INFO] ::1:55866 - "GET /favicon.ico HTTP/1.1" 404
14:07:31.78 [INFO] ::1:55865 - "POST /graphql HTTP/1.1" 200
```

This will start the Explorer Web UI server, which hosts the GraphQL API endpoint as well as other APIs. The `--graphql-open-graphiql` flag tells Pants to load the GraphiQL UI in your web browser, where you can explore the GraphQL schema.


Register custom API endpoints
-----------------------------

The API is a [`uvicorn`](https://www.uvicorn.org/) based server. To extend the API with more endpoints, register a union member of the `pants.backend.explorer.server.uvicorn.UvicornServerSetupRequest` and a rule that returns a `UvicornServerSetup`. The callback returned in the `UvicornServerSetup` response will be called with an instance of `pants.backend.explorer.server.uvicorn.UvicornServer` during server initialization to register API endpoints, middlewares and other configurations as required.


Register custom GraphQL schemas
-------------------------------

TBD.


Write frontend plugins
----------------------

TBD.
