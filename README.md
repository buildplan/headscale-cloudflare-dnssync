# headscale-cloudflare-dnssync (Fork by buildplan)

This is a fork of [marc1307/tailscale-cloudflare-dnssync](https://github.com/marc1307/tailscale-cloudflare-dnssync).
This version includes fixes for error reporting bugs encountered during API communication (ensuring clearer diagnostic messages) and has been tested with Headscale v0.25.1.

The script syncs Headscale (or Tailscale) node IPs to a Cloudflare-hosted DNS zone. This allows you to use your own custom domain for "MagicDNS-like" hostnames. A primary benefit is the ability to use standard SSL certificate providers like Let's Encrypt with the DNS-01 challenge for these hostnames, as they become publicly resolvable (though pointing to private Tailscale IPs).

## Features

* Adds IPv4 and IPv6 records for all devices to Cloudflare DNS.
* Removes DNS records for deleted/expired devices.
* Updates DNS records if a node's hostname/alias changes.
* Supports adding a prefix and/or postfix to DNS records.
* Includes a safety check to only attempt deletion of DNS records pointing to known Tailscale IP ranges (100.64.0.0/10 or fd7a:115c:a1e0::/48).
* Primarily focused on Headscale mode but retains Tailscale mode logic.
* Improved error reporting for API communication issues.

## Prerequisites

* Docker installed.
* A Cloudflare account and a domain managed by it.
* A Headscale instance.
* API Token for Cloudflare (scoped with DNS edit permissions for your zone).
* API Key for Headscale.

## Recommended Deployment: Docker Compose with `.env` File

This method is recommended for ease of configuration and secret management using the Docker image `iamdockin/hs-cf-dns-sync:0.0.2`.

**1. Prepare your Environment File**

Create an environment file (e.g., `dnssync.env`) in the same directory as your `docker-compose.yml` for this service. The script expects environment variables to be **lowercase** for most keys.

**Example `dnssync.env` for Headscale mode:**

```env
# ./dnssync.env
mode=headscale

# Cloudflare API Token (Zone:DNS:Edit permissions for cf_domain)
cf_key=YOUR_CLOUDFLARE_API_TOKEN
# Your root domain managed by Cloudflare (e.g., example.com)
cf_domain=yourdomain.com
# Optional: Subdomain to create records under (e.g., records become node.[cf_sub].yourdomain.com)
cf_sub=ts

# URL of your Headscale instance
hs_baseurl=[https://headscale.yourdomain.com](https://headscale.yourdomain.com)
# Headscale API key
hs_apikey=YOUR_HEADSCALE_API_KEY

# Optional: Prefix for DNS records (e.g., result: prefix-node.ts.yourdomain.com)
# prefix=
# Optional: Postfix for DNS records (e.g., result: node-postfix.ts.yourdomain.com)
# postfix=

# set sync interval - default is 15m
SYNC_INTERVAL_MINUTES=120

# for logs
PYTHONUNBUFFERED=1

````

**2. Create `docker-compose.yml` (or add to existing)**

Add this service definition:

```yaml
services:
  cloudflare-dns-sync:
    image: iamdockin/hs-cf-dns-sync:0.0.2
    container_name: cloudflare-dns-sync
    restart: unless-stopped
    pull_policy: always # Ensures you get updates if you retag the image
    env_file:
      - ./dnssync.env # Path to your environment file, relative to docker-compose.yml
    # This script is stateless beyond what tsnet might cache internally,
    # so specific data volumes are not strictly required for the script itself.
```

**3. Run the Container**

```bash
# If added to your main docker-compose.yml
docker compose up -d cloudflare-dns-sync

# If it's in its own docker-compose.yml in a subdirectory (e.g., ./dnssync-tool/docker-compose.yml)
# cd ./dnssync-tool
# docker compose up -d
```

Check logs to ensure it starts correctly and begins syncing:

```bash
docker compose logs -f cloudflare-dns-sync
```

## Alternative: `docker run` (Using `--env-file`)

1.  Prepare your `dnssync.env` file as shown above (using lowercase keys).

2.  Run the container:

    ```shell
    docker run -d --rm --name cloudflare-dns-sync \
      --env-file ./dnssync.env \
      iamdockin/hs-cf-dns-sync:0.0.2
    ```

    *(Use `-it` instead of `-d` for interactive mode to see logs directly).*

## How to Get API Keys/Tokens

### Cloudflare API Token

1.  Login to Cloudflare Dashboard.
2.  Go to "My Profile" (top right) -\> "API Tokens".
3.  Click "Create Token".
4.  Use the "Edit zone DNS" template or "Create Custom Token".
5.  **Permissions Required:** `Zone` - `DNS` - `Edit`.
6.  **Zone Resources:** `Include` - `Specific zone` - `<your_cf_domain_from_env_file>`.
7.  Create the token and copy it securely.

### Headscale API Key

1.  Connect to your Headscale server (e.g., via SSH if it's on a VPS).
2.  Generate an API key using the Headscale CLI. Replace `<your_headscale_container_name>` with the actual name of your Headscale Docker container (e.g., `headscale`).
    ```bash
    docker exec <your_headscale_container_name> headscale apikeys create --expiration 365d
    ```
    *(Adjust expiration as needed. This key is for the sync script to read data from Headscale).*
3.  Copy the generated key securely.

-----

*This fork maintains the core functionality of the original `marc1307/tailscale-cloudflare-dnssync` while incorporating fixes for improved error handling and has been tested primarily with Headscale.*
