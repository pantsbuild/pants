# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from .search_for_sonames import deb_packages_from_html_response

# simplified for readability and to keep it focused
SAMPLE_HTML_RESPONSE = """
<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
<html lang="en">
    <head><!-- ... --></head>
    <body>
        <div>...</div>
        <table>
            <tr><th>File</th><th>Packages</th></tr>
            <tr>
                <td class="file">/usr/lib/x86_64-linux-gnu/<span class="keyword">libldap-2.5.so.0</span></td>
                <td><a href="...">libldap-2.5.0</a> [amd64] </td>
            </tr>
            <tr>
                <td class="file">/usr/sbin/<span class="keyword">dnsmasq</span></td>
                <td><a href="...">dnsmasq-base</a>, <a href="...">dnsmasq-base-lua</a></td>
            </tr>
        </table>
        <div>...</div>
    </body>
</html>
"""


def test_deb_packages_from_html_response():
    results = list(deb_packages_from_html_response(SAMPLE_HTML_RESPONSE))
    assert results == [
        ("/usr/lib/x86_64-linux-gnu/libldap-2.5.so.0", ("libldap-2.5.0",)),
        ("/usr/sbin/dnsmasq", ("dnsmasq-base", "dnsmasq-base-lua")),
    ]
