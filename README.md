# oracle-a1-retry

Tries every 10 minutes to create the free Oracle Cloud A1 server `hermes-server`
(1 OCPU / 6 GB, Always Free) until Oracle has capacity. One request per run, no
automatic retries. On success it opens an issue (you get an email) and disables
itself.

Secrets (Settings → Secrets and variables → Actions): `OCI_USER`, `OCI_TENANCY`,
`OCI_FINGERPRINT`, `OCI_KEY` (the private key PEM). Nothing secret is in the code;
`hermes_key.pub` is an SSH **public** key.

Stop it any time: Actions → oracle-a1-retry → ⋯ → Disable workflow.
