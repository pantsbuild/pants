// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// This is the source code for a Cloudflare Worker that redirects requests
// (currently against static.pantsbuild.org) to https://pantsbuild.github.io
// and logs them with Google Analytics.
//
// (For context, a Cloudflare Worker (https://developers.cloudflare.com/workers/)
// is a cloud function that runs on the Cloudflare edge network.)
//
// To deploy this code, log in to our Cloudflare account, and go to
// Workers Routes > Manage Workers > redirect2githubpages > Quick edit. Then paste the
// code in the text area. You can use the UI to send a test request to test out
// your changes before clicking "Save and Deploy".

// Note that we have a proxied DNS A record pointing static.pantsbuild.org to a dummy IP.
// That is necessary for this worker to work.

// GA4_API_SECRET must be set under Settings > Variables > Environment Variables for the worker.
// The secret is obtained under "Measurement Protocol API secrets" on the stream details page
// in Google Analytics.
const apiSecret = GA4_API_SECRET;

// The measurement id is obtained from the stream details page in Google Analytics.
const measurementId = "G-Z7HQ5KDHDP";

const ga4URL = `https://www.google-analytics.com/mp/collect?measurement_id=${measurementId}&api_secret=${apiSecret}`;

function sendToGA4(headers, host, path) {
  const clientId = Math.random().toString(16).substring(2);
  const clientIP = headers.get("CF-Connecting-IP") || "";

  // GA drops hits with non-browser user agents on the floor,
  // including curl, which is what we expect people to mostly use.
  // So we detect if the userAgent isn't a browser,and adjust if so.
  let userAgent = headers.get("User-Agent") || "";
  if (
    !userAgent.toLowerCase().startsWith("mozilla") &&
    !userAgent.toLowerCase().startsWith("opera")
  ) {
    userAgent = ""; // GA accepts an empty user agent, go figure.
  }

  const events = [
    {
      name: "page_view",
      params: {
        page_host: host,
        page_path: path,
        ip: clientIP,
        user_agent: userAgent,
      },
    },
  ];

  const data = {
    client_id: clientId,
    events: events,
  };

  const payload = JSON.stringify(data);
  const gaHeaders = new Headers();
  gaHeaders.append("Content-Type", "application/json");
  return fetch(ga4URL, { method: "POST", headers: gaHeaders, body: payload });
}

// UA is being phased out in mid-2023, so we'll delete this once we have GA4 set up properly.
function sendToUA(headers, host, path) {
  const url = "https://www.google-analytics.com/collect";
  const uuid = Math.random().toString(16).substring(2);
  const clientIP = headers.get("CF-Connecting-IP") || "";

  // GA drops hits with non-browser user agents on the floor,
  // including curl, which is what we expect people to mostly use.
  // So we detect if the userAgent isn't a browser,and adjust if so.
  userAgent = headers.get("User-Agent") || "";
  if (
    !userAgent.toLowerCase().startsWith("mozilla") &&
    !userAgent.toLowerCase().startsWith("opera")
  ) {
    userAgent = ""; // GA accepts an empty user agent, go figure.
  }

  data = {
    v: "1",
    tid: "UA-78111411-2",
    cid: uuid,
    t: "pageview",
    dh: host,
    dp: path,
    uip: clientIP,
    ua: userAgent,
  };

  const payload = new URLSearchParams(data).toString();
  return fetch(url, { method: "POST", body: payload });
}

async function handleRequest(event) {
  const url = new URL(event.request.url);
  const { pathname, search } = url;
  const destinationURL = "https://pantsbuild.github.io" + pathname + search;
  event.waitUntil(
    Promise.all([
      sendToGA4(event.request.headers, url.host, pathname),
      sendToUA(event.request.headers, url.host, pathname),
    ])
  );
  return Response.redirect(destinationURL, 302);
}

addEventListener("fetch", async (event) => {
  event.respondWith(handleRequest(event));
});
