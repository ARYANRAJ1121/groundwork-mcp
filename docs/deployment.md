# Hosted deployment

This guide deploys the existing Docker Compose services on a Linux VPS: the OAuth-protected Streamable HTTP MCP endpoint and the public architecture-map page. It assumes you have a VPS, two DNS names, and a GitHub OAuth App. The SQLite database and downloaded repositories persist in the Compose volume mounted at `/data`.

## 1. Prepare the host and DNS

- Install Docker Engine with the Compose plugin.
- Point `mcp.<your-domain>` and `map.<your-domain>` to the VPS public IP.
- Allow inbound TCP ports 80 and 443 for HTTPS. Keep application ports 8000 and 8080 private to the host.
- Install Caddy on the host, or use another reverse proxy that supports HTTPS and WebSocket/streaming proxying.

Copy `deploy/Caddyfile.example` to the Caddy configuration location, replace both example hostnames, and reload Caddy. Caddy provisions and renews HTTPS certificates automatically when DNS and firewall routing are correct.

## 2. Create the GitHub OAuth App

Create a GitHub OAuth App under your GitHub account. Use the public MCP origin for its homepage and set its **Authorization callback URL** to:

```text
https://mcp.<your-domain>/auth/callback
```

FastMCP's GitHub provider uses `/auth/callback` by default. The callback URL must match exactly. This OAuth app signs users in; it does not grant Groundwork access to private repositories. The hosted service indexes public GitHub repositories only.

## 3. Configure secrets

On the VPS, clone this repository and create a private `.env` file from `deploy/.env.example`. Fill in the OAuth app ID and secret, set the MCP base URL to `https://mcp.<your-domain>`, and create a random signing key with at least 32 characters. For example, on Linux:

```bash
openssl rand -hex 32
```

Keep the real `.env` file off Git and make a secure backup of the signing key. Changing that key invalidates existing issued tokens.

## 4. Start and verify

From the repository root on the VPS:

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 mcp web
```

The Compose file currently builds from the checkout. To use the published image instead, change `build: .` for each service to `image: ghcr.io/aryanraj1121/groundwork-mcp:v0.6.0`, then run `docker compose pull` before starting. Keep a persistent backup of the `groundwork-data` volume.

Check that `https://mcp.<your-domain>/mcp` is reachable and that the client is prompted to authorize through GitHub. Visit `https://map.<your-domain>` and submit a public repository URL. The first request indexes the repository; later requests can reuse the commit-keyed snapshot.

## 5. Connect an MCP client

In a client that supports remote Streamable HTTP MCP servers with OAuth, add the server URL:

```text
https://mcp.<your-domain>/mcp
```

The client should discover the OAuth metadata and open GitHub sign-in. Local stdio mode remains the recommended option for private repositories and local workspaces; never put a user's private source into a shared hosted index.

## Marketplace publication

The extension release workflow is `.github/workflows/publish-vscode.yml`. Before its first run:

1. Create the `groundwork-mcp` publisher in the [Visual Studio Marketplace publisher portal](https://marketplace.visualstudio.com/manage).
2. In that publisher's **Trusted Publishing** page, create a policy for GitHub owner `ARYANRAJ1121`, repository `groundwork-mcp`, workflow `publish-vscode.yml`; leave Environment empty.
3. Run **Actions → Publish VS Code extension → Run workflow** to publish the current manifest version (`0.1.0`).

For each later extension release, increment `extensions/vscode/package.json` and its lockfile version, commit and push, then create a tag named `vscode-v<version>` (for example `vscode-v0.1.1`). The workflow checks that the tag and manifest versions match before publishing. It uses Marketplace OIDC trusted publishing; no PAT secret is required.
