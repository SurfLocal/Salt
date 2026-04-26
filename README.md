<p align="center">
  <img src="https://github.com/SurfLocal/Salt/blob/media/logos/logo1.png?raw=true" width="250" alt="Project Logo">
</p>

# Salt

This is a surfing app that integrates AI-powered swell and condition forecasting, alongside a social platform for surfers to connect and share their sessions. Users can log their surf sessions, share insights, and interact with others within the surfing community.

## Contributing

We welcome contributions to this project! If you're interested in contributing, please read our [Contributing Guidelines](CONTRIBUTING.md) for details on how to get started.

By following these guidelines, you'll help us maintain a consistent development process and ensure a smooth experience for all contributors.

## Key Features:
- AI-Driven Forecasting: Get accurate swell and condition forecasts based on AI models.
- Session Logging: Log details of your surf sessions, including date, time, surf spot, wave conditions, and more.
- Social Interaction: Connect with other surfers, share session details, and interact with the community.
- Real-Time Data: AI-powered predictions for surf conditions, utilizing web scraping to gather data.

## Directory Structure

```
Salt/
├── .github/                    # GitHub Actions workflows
│   └── workflows/
│       ├── docker-build-api.yml      # API image builds
│       ├── docker-build-app.yml      # App image builds
│       └── docker-build-scraper.yml  # Scraper image builds
├── ansible/                    # Infrastructure automation
│   ├── ansible.cfg
│   ├── hosts                   # Inventory file
│   ├── playbooks/
│   │   ├── deploy_cluster.yaml
│   │   ├── deploy_common.yaml
│   │   ├── deploy_coredns.yaml
│   │   ├── deploy_docker.yaml
│   │   ├── deploy_helm.yaml
│   │   ├── deploy_kubernetes.yaml
│   │   ├── deploy_node_exporter.yaml
│   │   ├── deploy_noip.yaml
│   │   ├── deploy_postgres.yaml
│   │   ├── deploy_postgres_exporter.yaml
│   │   ├── deploy_s3_storage.yaml
│   │   └── site.yaml
│   ├── roles/                  # Ansible roles for each service
│   └── vars/                   # Variable files (secrets encrypted)
├── api/                        # Backend API (Express.js + TypeScript)
│   ├── src/                    # Source code
│   ├── tests/                  # Unit and integration tests
│   └── salt-api.Dockerfile     # Docker build configuration
├── app/                        # Frontend application (React + Vite)
│   ├── src/                    # Source code
│   ├── tests/                  # Unit and integration tests
│   └── salt-app.Dockerfile     # Docker build configuration
├── helm/                       # Kubernetes application deployments
│   ├── STANDARDS.md           # Helm chart conventions
│   ├── argo-workflows/        # Workflow orchestration
│   ├── grafana/               # Monitoring dashboards
│   ├── minio/                 # S3-compatible object storage
│   ├── prometheus/            # Metrics collection
│   ├── salt-api/              # Backend API deployment
│   └── salt-app/              # Frontend app deployment
├── networking/                 # Network setup scripts
│   ├── boot_pi.sh
│   └── init_host.sh
├── postgres/                   # Database configuration
│   ├── databases/
│   ├── roles/
│   └── users/
├── web-scraping/              # Data collection jobs
│   ├── jobs/
│   │   └── tests/             # Scraper tests
│   ├── web-scraper.Dockerfile
│   └── requirements.txt
└── README.md
```

## Getting Started

### Clone this Git Repository

Clone the repository and navigate into it:
```bash
git clone https://github.com/SurfLocal/Salt.git
cd Salt
```

## Deployment paths

Salt has two supported deployment modes:

| Mode | Where | When to use | Cost |
|---|---|---|---|
| **Tier A — cloud, free tier** | Cloud Run + Neon Postgres + Cloudflare R2 + Pages | Test users, MVP, anything internet-facing | ~$0–10/mo |
| **Self-hosted (legacy POC)** | Raspberry Pi K3s cluster (Ansible + Helm) | Local lab, original POC, learning K8s | hardware cost |

The Kubernetes/Helm/Ansible flow below remains supported for the original Pi cluster but is **not** the recommended path for putting the app in front of users. Use Tier A for that.

## Tier A deployment (cloud, free tier)

The Tier A infrastructure is defined as Terraform in a separate repo: [`gcp-salt/gcp/terraform/tier-a-infra/`](../gcp-salt/gcp/terraform/tier-a-infra/). It provisions a GCP Artifact Registry, Cloud Run service + jobs, Secret Manager, Cloud Scheduler, plus a Neon Postgres project and a Cloudflare R2 bucket. See that repo's README for the full apply order (4 sub-stacks: `00-bootstrap` → `10-data-stores` → `20-runtime` → `30-dns`).

### How the app maps onto Tier A

| Component | Hosted on | Image source |
|---|---|---|
| `app/` (React SPA) | **Cloudflare Pages** — built from this repo on every push | git-driven, no docker push |
| `api/` (Express API) | **Cloud Run service** `salt-api` | `api/salt-api.Dockerfile` → Artifact Registry |
| `web-scraping/jobs/` (Python scrapers) | **Cloud Run Jobs** `salt-scraper-swell`, `salt-scraper-wind` | `web-scraping/web-scraper.Dockerfile` → Artifact Registry |
| Postgres | **Neon free** — `salt_app` + `surf_analytics` databases | n/a |
| Object storage | **Cloudflare R2** — single bucket, prefix-based logical buckets | n/a |
| Secrets | **GCP Secret Manager** | populated from Terraform |

### Environment variables Cloud Run sets

The Tier A Terraform wires these into Cloud Run automatically. The app code reads them in `api/src/config/database.ts` and `api/src/config/minio.ts`.

| Var | Source | Purpose |
|---|---|---|
| `DATABASE_URL` | SM secret `salt-database-url` | Neon `salt_app` connection string |
| `ANALYTICS_DATABASE_URL` | SM secret `salt-analytics-database-url` | Neon `surf_analytics` (used by `analyticsQuery`) |
| `JWT_SECRET` | SM secret `salt-jwt-secret` | API token signing |
| `STORAGE_PROVIDER`, `STORAGE_BUCKET`, `STORAGE_REGION` | plain env | R2 routing |
| `STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY` | SM secrets | R2 S3-compat credentials |
| `STORAGE_PUBLIC_BASE_URL` | SM secret `salt-storage-public-base-url` | Public base URL for stored media (`pub-XXX.r2.dev` or `media.surflocal.app`) |
| `BUCKET_SESSION_MEDIA`, `BUCKET_AVATARS`, `BUCKET_BOARD_PHOTOS` | plain env | object-key prefixes inside the single R2 bucket |
| `CORS_ORIGIN` | plain env | set to `https://app.surflocal.app` |
| `OPENWEATHER_API_KEY` | SM secret (scrapers only) | wind data |

Local docker-compose dev keeps working because the configs fall back to legacy `MINIO_*` and `DATABASE_HOST/USER/PASSWORD/NAME` when `STORAGE_ENDPOINT` / `DATABASE_URL` are unset.

### Building + pushing images for Tier A

After `gcp-salt/gcp/terraform/tier-a-infra/00-bootstrap` and `20-runtime` are applied, push images from the SurfLocal repo root:

```bash
cd /path/to/SurfLocal

# Pull the registry path + image refs out of Terraform state.
# (Run from the terraform sub-stacks; copy the values back here.)
REGISTRY_HOST=us-west1-docker.pkg.dev
API_IMG=us-west1-docker.pkg.dev/<project_id>/salt-docker-repo/salt-api:latest
SCRAPER_IMG=us-west1-docker.pkg.dev/<project_id>/salt-docker-repo/salt-scraper:latest

gcloud auth configure-docker "$REGISTRY_HOST"

# API
docker build -f api/salt-api.Dockerfile -t "$API_IMG" .
docker push "$API_IMG"
gcloud run services update salt-api --region us-west1 --image "$API_IMG"

# Scraper (one image, two jobs reuse it via different commands)
docker build -f web-scraping/web-scraper.Dockerfile -t "$SCRAPER_IMG" .
docker push "$SCRAPER_IMG"
gcloud run jobs update salt-scraper-swell --region us-west1 --image "$SCRAPER_IMG"
gcloud run jobs update salt-scraper-wind  --region us-west1 --image "$SCRAPER_IMG"
```

A first apply uses `gcr.io/cloudrun/hello` as a placeholder; replace it with the real image as soon as you've built it. The Terraform `lifecycle.ignore_changes` block on `containers[0].image` prevents subsequent applies from reverting your push.

### Dockerfile requirements for Cloud Run

Both Dockerfiles need to honor Cloud Run conventions:

- Listen on `$PORT` (default `8080`). The API config reads `PORT` from env and the entrypoint is `npm start` → `node dist/index.js`.
- Provide a `/health` endpoint (already implemented at [api/src/index.ts:47](api/src/index.ts#L47)).
- Image runs as non-root in production builds (preferred but not required by Cloud Run).

If `api/salt-api.Dockerfile` or `web-scraping/web-scraper.Dockerfile` were originally tuned for K3s, double-check the `EXPOSE` / `CMD` lines match the above before pushing.

### Schema bootstrap (one-time)

Tier A Postgres is empty on first apply. From `gcp-salt/gcp/terraform/tier-a-infra/10-data-stores/`:

```bash
DB_URL=$(terraform output -raw neon_database_url)
ANALYTICS_URL=$(terraform output -raw neon_analytics_database_url)

# salt_app
psql "$DB_URL" -f /path/to/SurfLocal/postgres/databases/salt_app/database.sql
for f in /path/to/SurfLocal/postgres/databases/salt_app/{schemas,tables,functions,triggers}/*.sql; do
  psql "$DB_URL" -f "$f"
done

# surf_analytics
for f in /path/to/SurfLocal/postgres/databases/surf_analytics/{schemas,tables}/*.sql; do
  psql "$ANALYTICS_URL" -f "$f"
done
```

Use the connection-string-aware functions in [api/src/config/database.ts](api/src/config/database.ts) — they handle Neon's pooled host transparently.

### Frontend deploy (Cloudflare Pages)

When `30-dns` is applied with `github_repo` set, Cloudflare Pages connects to the GitHub repo and rebuilds on every push to `main`. Build command: `cd app && npm ci && npm run build`. Output: `app/dist`. Pages injects `VITE_API_URL` (pointing at `https://api.surflocal.app` once DNS is on) and `VITE_MAPBOX_TOKEN` at build time.

Until nameservers are switched, the frontend is reachable at `https://salt-app-dev.pages.dev` (or whatever name Cloudflare assigns) — set `VITE_API_URL` to the Cloud Run URL temporarily if you need an end-to-end test before DNS cutover.

### Smoke test

```bash
# Cloud Run URL (from `cd 20-runtime && terraform output -raw api_url`)
curl https://salt-api-XXXXXX-uw.a.run.app/health
curl https://salt-api-XXXXXX-uw.a.run.app/health/db
```

After DNS cutover:
```bash
curl https://api.surflocal.app/health
```

## Self-hosted Pi cluster (legacy)

The sections below describe the original POC deployment on Raspberry Pi K3s. Use this for local lab work; for putting Salt in front of users, use Tier A above.

### Networking Components

The README in the `networking/` directory provides a detailed guide for setting up networking configurations on Raspberry Pi nodes. It begins with instructions for installing the Raspberry Pi OS and configuring hostnames. The first step involves using the Raspberry Pi Imager to install the OS, where users are prompted to configure a username and password for enabling SSH access. After the OS installation, the 'boot_pi.sh' script is executed to set a unique hostname for each Raspberry Pi and ensure SSH is enabled. This automates the pre-boot configuration, making it easier to prepare the devices for remote access.

Next, the `init_host.sh` script is used once the Raspberry Pis are booted and connected to the local network. This script facilitates the setup of secure, passwordless SSH access by generating and transferring SSH keys, and disabling password authentication on the remote machine for enhanced security. The README emphasizes that each Raspberry Pi should be configured with a specific hostname and ensures that SSH access is set up correctly for future, seamless connections.

### Ansible Provisioning

The Ansible playbooks automate the installation and configuration of essential tools for setting up a containerized and Kubernetes-based environment. It begins by installing Docker on ARM64 systems, adding the necessary GPG key and repository, and ensuring that the user can run Docker commands without sudo. Helm, a package manager for Kubernetes, is also installed by downloading and executing its installation script.

The playbooks then handle the installation and configuration of K3s, a lightweight Kubernetes distribution. The master node is initialized and the necessary join token is retrieved to add worker nodes to the cluster. Systemd services are enabled for both the K3s master and worker nodes to ensure they start automatically on boot. Additionally, Node Exporter is installed to collect system metrics for Prometheus monitoring, and the No-IP Dynamic Update Client (DUC) is configured for dynamic DNS management.

Finally, PostgreSQL is installed and configured to run with its data directory stored on a larger partition. The playbooks ensure PostgreSQL is set up to listen on both localhost and Kubernetes nodes and create a custom systemd service to manage its startup. These playbooks streamline the setup process by automating the installation and configuration of critical tools for development or production environments.

### Helm Deployments

Once the infrastructure for Kubernetes and PostgreSQL is set up, applications and workflows are managed and deployed to the cluster using Helm. Helm simplifies the deployment process by providing a consistent, repeatable way to manage Kubernetes applications.

**Current Deployments:**
- **Argo Workflows**: Orchestrates scheduled data scraping jobs (hourly swell and wind data collection)
- **MinIO**: S3-compatible object storage for workflow logs and artifacts (100Gi SSD storage)
- **Prometheus**: Metrics collection and monitoring for all cluster nodes and PostgreSQL database

All Helm charts follow standardized conventions documented in `helm/STANDARDS.md`, ensuring consistent structure, proper templating, and maintainability. See the [Helm README](helm/README.md) for detailed deployment instructions.

### Install Dependencies

#### Steps for MacOS

1. **Install Homebrew:**
   If Homebrew is not installed, install it by running:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Install Ansible:**
   ```bash
   brew install ansible
   ```

3. **Install `iproute2mac`:** The `ip` command (part of `iproute2mac`) is used to retrieve the router IP and perform other network-related tasks.
   ```bash
   brew install iproute2mac
   ```
