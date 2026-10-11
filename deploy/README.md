# deploy/

Files the production stack reads at runtime and that must never be committed.

## `certs/`

nginx expects two files here, mounted read-only into the `web` container:

| File | What |
|---|---|
| `certs/tls.crt` | Server certificate (include the intermediate chain). |
| `certs/tls.key` | Its private key. |

- **Real deployment:** use a certificate from a CA (for example Let's Encrypt via certbot on the host, or your
  organization's PKI) and renew it before it expires. Copy or symlink the files here, then
  `docker compose --env-file .env.prod -f docker-compose.prod.yml restart web`.
- **Trying it on a workstation:** `./infrastructure/scripts/make_dev_cert.sh` writes a 30-day **self-signed**
  certificate for `localhost`. Browsers warn about it; that is expected.

Everything in `certs/` except `.gitkeep` is git-ignored.
