# Authenticate to a Server

## Problem

Some Pants operations talk to remote servers. Examples include uploading build stats, querying remote caches 
and resolving external dependencies.  But in some cases these servers may only allow access to authenticated users. 

## Solution

Currently Pants only supports HTTP basic auth.  How you use this depends on what the server expects:

If the endpoints you're accessing (e.g., the build stats upload endpoint or the remote cache query endpoint)
accept HTTP basic auth credentials directly, you only need add those creds to a `.netrc` entry for 
that server.
  
However, in many cases the server expects you to provide credentials to an authentication endpoint, 
in exchange for a session id, and then provide that session id in subsequent requests to the other endpoints.

In the latter case, you can perform that authentication using the `login` goal, and specifying the 
provider you're authenticating against with the `--to` option:

```bash
$ ./pants login --to=myauthprovider
```

This submits credentials from `.netrc` to the provider's authentication endpoint using HTTP basic auth, 
and stores all returned cookies (which, presumably, include the session id), for future use with the other 
endpoints.

In the future, the `login` goal will optionally prompt for a username and password, allowing you to
bypass `.netrc` altogether.


## Required Configuration

The named provider must be configured. E.g., in `pants.toml` you'd have:

```toml
[basic_auth]
providers = """
{
  'myauthprovider': {
    'url': 'https://myauthprovider.com/path/to/authentication/endpoint'
  }
}
"""
```
