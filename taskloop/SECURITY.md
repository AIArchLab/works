# Security scope

This is a bounded local CLI MVP, not a multi-tenant public API. Do not embed credentials in URLs.
Use exact host allowlists, HTTPS, a strong shared webhook secret and persistent private storage.
The sample inbox server is for local integration; expose it only behind HTTPS and appropriate
network/authentication controls. A human-read receipt and separate operational escalation channel
are outside this release. Report suspected vulnerabilities privately through the repository owner's
established contact route; never paste working secrets or exploit payloads into public issues.
