# Salt App - Google Cloud Platform Migration Plan

**Prepared for:** SurfLocal Salt Project  
**Date:** January 8, 2026  
**Scope:** Migrate from self-hosted Kubernetes on Raspberry Pi to serverless Google Cloud infrastructure

---

## Executive Summary

This document outlines a comprehensive migration strategy for transitioning Salt from a self-hosted Raspberry Pi Kubernetes cluster to a **serverless, cloud-native architecture on Google Cloud Platform**. The migration leverages Cloud Run for containerized workloads, Cloud SQL for databases, Cloud Storage for media, Pub/Sub for async processing, and Cloud Tasks for scheduled jobs.

**Key Benefits:**
- 🎯 **Zero infrastructure management** - No servers to maintain
- 💰 **Cost-efficient** - Pay only for compute used (ideal for variable workloads)
- 🚀 **Auto-scaling** - Handle traffic spikes automatically
- 🌍 **Global distribution** - Serve content from Google's edge network
- 📊 **Built-in monitoring** - Cloud Logging and Cloud Trace integration
- 🔒 **Enterprise security** - VPC, IAM, encryption at rest/transit

---

## Current Architecture Summary

### Components to Migrate

| Component | Current Tech | Current Role | Complexity |
|-----------|--------------|--------------|-----------|
| **Backend API** | Express.js + Node.js | REST API server | Medium |
| **Frontend** | React + Nginx | Web UI | High (CDN needed) |
| **Web Scraper** | Python | Scheduled data collection | Medium |
| **Database** | PostgreSQL (bare metal) | Primary data store | Medium |
| **Object Storage** | MinIO (self-hosted) | Media files | Low |
| **Monitoring** | Prometheus + Grafana | Observability | Optional |
| **Workflows** | Argo Workflows | Job orchestration | Medium |

### Current Data Dependencies

```
Frontend → API (JWT auth, REST calls)
API → PostgreSQL (user data, sessions, boards, social)
API → MinIO (media uploads/downloads)
Scraper (Python) → NOAA + OpenWeather APIs → PostgreSQL + MinIO
Frontend → Mapbox (maps)
Frontend → MinIO (media URLs)
```

---

## Proposed GCP Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                      Google Cloud Platform                       │
│                                                                 │
│  ┌─────────────────────────────────────────────────────┐        │
│  │         Cloud CDN + Cloud Armor (Security)         │        │
│  └────────────────────┬────────────────────────────────┘        │
│                       │                                         │
│       ┌───────────────┴────────────────┬──────────────┐        │
│       │                                │              │        │
│  ┌────▼──────┐                  ┌─────▼────┐    ┌───▼────┐    │
│  │ Cloud Run │                  │ Cloud Run │    │ Cloud  │    │
│  │ Frontend  │                  │  API     │    │ Storage│    │
│  │(React SPA)│                  │(Express) │    │ (Media)│    │
│  └───────────┘                  └────┬─────┘    └────────┘    │
│                                       │                        │
│                    ┌──────────────────┼──────────────┐        │
│                    │                  │              │        │
│              ┌─────▼──────┐    ┌──────▼────┐  ┌────▼─────┐   │
│              │  Cloud SQL  │    │  Pub/Sub  │  │ Cloud    │   │
│              │ PostgreSQL  │    │(Async Job)│  │ Tasks    │   │
│              └─────────────┘    └───────────┘  │(Scheduler)   │
│                                                └──────────┘   │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Monitoring: Cloud Logging, Cloud Trace, Cloud       │   │
│  │  Monitoring (dashboards with Cloud Console)           │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

External APIs:
├── Mapbox (maps & geocoding)
├── NOAA (buoy data for scraping)
└── OpenWeather (weather forecasting)
```

### Service Mapping

| Old | New | Service | Type |
|-----|-----|---------|------|
| Express API | salt-api-cloud-run | Cloud Run | Serverless Container |
| React + Nginx | salt-app-cloud-run | Cloud Run | Serverless Container |
| PostgreSQL | salt-postgres-cloudsql | Cloud SQL | Managed Database |
| MinIO | salt-media-bucket | Cloud Storage | Object Storage |
| Scraper Jobs | salt-scraper-cloud-run | Cloud Run Jobs | Scheduled Jobs |
| Argo Workflows | Cloud Tasks + Cloud Scheduler | Cloud Tasks + Scheduler | Job Orchestration |
| Monitoring | Cloud Logging + Cloud Monitoring | Native GCP | Observability |

---

## Detailed Migration Strategy

### Phase 1: Foundation Setup (Week 1-2)

#### 1.1 Create GCP Project & Enable APIs

```bash
# Set project variables
export PROJECT_ID="salt-surf-app"
export REGION="us-central1"

# Create project
gcloud projects create $PROJECT_ID --name="Salt Surf App"
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  sql.googleapis.com \
  storage.googleapis.com \
  cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com \
  container.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  compute.googleapis.com \
  servicenetworking.googleapis.com
```

#### 1.2 Set Up VPC & Networking

```bash
# Create VPC for private connectivity
gcloud compute networks create salt-vpc \
  --subnet-mode=custom \
  --bgp-routing-mode=regional

# Create private subnet
gcloud compute networks subnets create salt-private-subnet \
  --network=salt-vpc \
  --range=10.0.1.0/24 \
  --region=$REGION

# Create Cloud NAT for private egress
gcloud compute routers create salt-router \
  --network=salt-vpc \
  --region=$REGION

gcloud compute routers nats create salt-nat \
  --router=salt-router \
  --region=$REGION \
  --nat-all-subnet-ip-ranges \
  --auto-allocate-nat-external-ips
```

#### 1.3 Set Up Private Service Connection

```bash
# Reserve IP range for private services
gcloud compute addresses create google-managed-services-salt-vpc \
  --global \
  --purpose=VPC_PEERING \
  --prefix-length=16 \
  --network=salt-vpc

# Create private connection
gcloud services vpc-peerings connect \
  --service=servicenetworking.googleapis.com \
  --ranges=google-managed-services-salt-vpc \
  --network=salt-vpc
```

**Deliverables:**
- [ ] GCP project created
- [ ] All required APIs enabled
- [ ] VPC and subnet configured
- [ ] Private service connection established

---

### Phase 2: Database Migration (Week 2-3)

#### 2.1 Set Up Cloud SQL Instance

```bash
# Create Cloud SQL PostgreSQL instance
gcloud sql instances create salt-postgres-prod \
  --database-version=POSTGRES_15 \
  --tier=db-custom-2-8192 \
  --region=$REGION \
  --network=projects/$PROJECT_ID/global/networks/salt-vpc \
  --no-public-ip \
  --backup-start-time=03:00 \
  --enable-bin-log \
  --retained-backups-count=30 \
  --transaction-log-retention-days=7 \
  --backup-configuration=enabled=true,location=us,point-in-time-recovery-enabled=true
```

**Configuration Details:**
- **Instance Type:** `db-custom-2-8192` (2 vCPU, 8GB RAM) - can scale as needed
- **Backup Strategy:** Daily + point-in-time recovery (PITR)
- **Network:** Private IP only (no public internet exposure)
- **HA:** Consider upgrading to HA configuration for production

#### 2.2 Create Databases & Service Accounts

```bash
# Connect to the instance
gcloud sql connect salt-postgres-prod --user=postgres

# Inside psql:
CREATE DATABASE salt_app;

-- Create service account for application
CREATE USER salt_app_user WITH PASSWORD 'SECURE_PASSWORD_HERE';
GRANT CONNECT ON DATABASE salt_app TO salt_app_user;

-- Switch to salt_app database
\c salt_app

-- Create schemas (based on current setup)
CREATE SCHEMA auth;
CREATE SCHEMA public;

-- Grant permissions
GRANT USAGE ON SCHEMA auth, public TO salt_app_user;
GRANT CREATE ON SCHEMA auth, public TO salt_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth, public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO salt_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth, public GRANT USAGE ON SEQUENCES TO salt_app_user;
```

#### 2.3 Migrate Data from PostgreSQL

**Option A: Using pg_dump (Recommended for smaller databases)**

```bash
# On your local machine with current PostgreSQL access
pg_dump -h <current_db_host> -U <current_user> -d salt_app > salt_app_backup.sql

# Restore to Cloud SQL
gcloud sql import sql salt-postgres-prod \
  gs://salt-backup-bucket/salt_app_backup.sql \
  --database=salt_app
```

**Option B: Using Database Migration Service (for large databases)**

This is a more robust approach for production migrations with minimal downtime.

```bash
# Enable DMS API
gcloud services enable datamigration.googleapis.com

# Create migration job (through Cloud Console recommended)
# This provides continuous replication until cutover
```

**Deliverables:**
- [ ] Cloud SQL instance provisioned
- [ ] Databases and schemas created
- [ ] Service accounts configured
- [ ] Data migrated and validated
- [ ] Connection pooling configured

---

### Phase 3: Storage Setup (Week 2)

#### 3.1 Create Cloud Storage Buckets

```bash
# Create main media bucket
gsutil mb -p $PROJECT_ID -l $REGION gs://salt-media-prod

# Create staging bucket for temporary uploads
gsutil mb -p $PROJECT_ID -l $REGION gs://salt-media-staging

# Create backup/archive bucket
gsutil mb -p $PROJECT_ID -l $REGION gs://salt-backups

# Set bucket lifecycle policies
cat > lifecycle.json << EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {"age": 30}
      },
      {
        "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF

gsutil lifecycle set lifecycle.json gs://salt-media-prod
```

#### 3.2 Configure Signed URLs & Access Control

```bash
# Create service account for Cloud Run API access
gcloud iam service-accounts create salt-api-sa \
  --display-name="Salt API Service Account"

# Grant Cloud Storage permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/storage.objectCreator

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/storage.objectViewer
```

#### 3.3 Enable CDN for Media Delivery

```bash
# Create backend bucket for Cloud CDN
gcloud compute backend-buckets create salt-media-backend \
  --gcs-bucket-name=salt-media-prod \
  --enable-cdn \
  --cache-mode=CACHE_ALL_STATIC

# Set CDN cache TTL (24 hours for media)
gcloud compute backend-buckets update salt-media-backend \
  --client-ttl=86400 \
  --default-ttl=3600 \
  --max-ttl=86400
```

**Deliverables:**
- [ ] Cloud Storage buckets created
- [ ] Lifecycle policies configured
- [ ] Service accounts and IAM roles set up
- [ ] CDN enabled and configured

---

### Phase 4: Containerization & Artifact Registry (Week 3)

#### 4.1 Create Artifact Registry

```bash
# Create Docker repository
gcloud artifacts repositories create salt-docker-repo \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker images for Salt app"

# Configure Docker authentication
gcloud auth configure-docker $REGION-docker.pkg.dev
```

#### 4.2 Update & Build Docker Images

**Backend API Dockerfile Updates:**

The existing Dockerfile is mostly compatible. Key changes:

```dockerfile
# api/salt-api.Dockerfile - UPDATED FOR CLOUD RUN

# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY api/package*.json ./
RUN npm ci
COPY api/tsconfig.json ./
COPY api/src ./src
RUN npm run build

# Production stage
FROM node:20-alpine

ARG NODE_ENV=production
ENV NODE_ENV=$NODE_ENV

WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY api/package.json ./

# Cloud Run requires PORT env var
ENV PORT=8080
EXPOSE 8080

# Health check for Cloud Run
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:8080/health', (r) => {if (r.statusCode !== 200) throw new Error(r.statusCode)})"

CMD ["npm", "start"]
```

**Frontend Dockerfile Updates:**

```dockerfile
# app/salt-app.Dockerfile - UPDATED FOR CLOUD RUN

FROM node:20-alpine AS builder

ARG VITE_API_URL
ARG VITE_MINIO_URL
ARG VITE_MAPBOX_TOKEN

ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_MINIO_URL=${VITE_MINIO_URL}
ENV VITE_MAPBOX_TOKEN=${VITE_MAPBOX_TOKEN}

WORKDIR /app
COPY app/package*.json ./
RUN npm ci
COPY app/ .
RUN npm run build

# Serve with Cloud Run-compatible web server
FROM node:20-alpine AS runtime
WORKDIR /app
RUN npm install -g http-server
COPY --from=builder /app/dist ./public

ENV PORT=8080
EXPOSE 8080

CMD ["http-server", "public", "-p", "8080", "--cors"]
```

**Alternative: Use Nginx for production frontend:**

```dockerfile
# app/salt-app.Dockerfile - USING NGINX

FROM node:20-alpine AS builder
# ... (same build steps)

FROM nginx:alpine
COPY app/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html

ENV PORT=8080
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
```

#### 4.3 Build and Push Images

```bash
# Set up Cloud Build for automated builds
gcloud builds submit \
  --substitutions=_REGION="$REGION" \
  --config=cloudbuild.yaml

# Or manually build and push
# Backend API
docker build -f api/salt-api.Dockerfile \
  -t $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-api:latest \
  -t $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-api:v1.0.0 \
  .

docker push $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-api:latest

# Frontend App
docker build -f app/salt-app.Dockerfile \
  -t $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-app:latest \
  -t $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-app:v1.0.0 \
  --build-arg VITE_API_URL="https://api.salt.app" \
  --build-arg VITE_MINIO_URL="https://media.salt.app" \
  --build-arg VITE_MAPBOX_TOKEN="$MAPBOX_TOKEN" \
  .

docker push $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-app:latest
```

**Deliverables:**
- [ ] Artifact Registry repository created
- [ ] Dockerfiles updated for Cloud Run
- [ ] Cloud Build pipeline configured
- [ ] Images built and pushed

---

### Phase 5: Deploy Backend API to Cloud Run (Week 3-4)

#### 5.1 Create Cloud Run Service for API

```bash
# Deploy Backend API
gcloud run deploy salt-api \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-api:latest \
  --platform=managed \
  --region=$REGION \
  --no-allow-unauthenticated \
  --service-account=salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --vpc-connector=salt-vpc-connector \
  --vpc-egress=private-ranges-only \
  --set-env-vars="NODE_ENV=production" \
  --set-env-vars="PORT=8080" \
  --set-env-vars="LOG_LEVEL=info" \
  --set-env-vars="CORS_ORIGIN=https://salt.app" \
  --set-env-vars="DB_HOST=/cloudsql/$PROJECT_ID:$REGION:salt-postgres-prod" \
  --set-env-vars="DB_NAME=salt_app" \
  --set-env-vars="DB_USER=salt_app_user" \
  --set-env-vars="DB_PORT=5432" \
  --add-cloudsql-instances=$PROJECT_ID:$REGION:salt-postgres-prod \
  --memory=512Mi \
  --cpu=1 \
  --timeout=60 \
  --max-instances=50 \
  --min-instances=1
```

#### 5.2 Set Up Cloud SQL Proxy

Cloud Run services connect to Cloud SQL via the Cloud SQL Proxy Unix socket:

```bash
# Create VPC Connector for Cloud SQL access
gcloud compute networks vpc-access connectors create salt-vpc-connector \
  --region=$REGION \
  --subnet=salt-private-subnet \
  --min-throughput=200 \
  --max-throughput=1000
```

#### 5.3 Configure Secrets Manager

```bash
# Store database password
echo -n "SECURE_DB_PASSWORD" | \
  gcloud secrets create db-password --data-file=-

# Store JWT secret
echo -n "SECURE_JWT_SECRET" | \
  gcloud secrets create jwt-secret --data-file=-

# Grant Cloud Run service account access
gcloud secrets add-iam-policy-binding db-password \
  --member=serviceAccount:salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

# Update Cloud Run to use secrets
gcloud run deploy salt-api \
  --update-secrets=DB_PASSWORD=db-password:latest \
  --update-secrets=JWT_SECRET=jwt-secret:latest \
  --region=$REGION
```

#### 5.4 Set Up API Gateway & Authentication

```bash
# Create service account for unauthenticated frontend requests
gcloud iam service-accounts create salt-frontend-sa \
  --display-name="Salt Frontend Service Account"

# Grant Cloud Run Invoker role to frontend
gcloud run add-iam-policy-binding salt-api \
  --member=serviceAccount:salt-frontend-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/run.invoker \
  --region=$REGION
```

**Deliverables:**
- [ ] Cloud Run service deployed
- [ ] VPC Connector configured
- [ ] Secrets Manager set up
- [ ] Environment variables configured
- [ ] Database connectivity verified

---

### Phase 6: Deploy Frontend to Cloud Run (Week 4)

#### 6.1 Deploy Frontend Service

```bash
# Deploy Frontend App
gcloud run deploy salt-app \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-app:latest \
  --platform=managed \
  --region=$REGION \
  --allow-unauthenticated \
  --service-account=salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --memory=256Mi \
  --cpu=1 \
  --timeout=30 \
  --max-instances=30 \
  --min-instances=1
```

#### 6.2 Set Up Cloud Load Balancer with CDN

```bash
# Create health check
gcloud compute health-checks create http salt-app-health \
  --request-path=/health \
  --check-interval=30s

# Create backend service
gcloud compute backend-services create salt-app-backend \
  --health-checks=salt-app-health \
  --global \
  --enable-cdn \
  --cache-mode=CACHE_ALL_STATIC \
  --client-ttl=3600 \
  --default-ttl=3600 \
  --max-ttl=86400

# Create Network Endpoint Group (NEG) for Cloud Run
gcloud compute network-endpoint-groups create salt-app-neg \
  --region=$REGION \
  --network-endpoint-type=SERVERLESS \
  --cloud-run-service=salt-app
```

#### 6.3 Set Up Custom Domain & DNS

```bash
# Add backend to service
gcloud compute backend-services add-backend salt-app-backend \
  --global \
  --instance-group=salt-app-neg \
  --instance-group-region=$REGION

# Create URL map
gcloud compute url-maps create salt-app-lb \
  --default-service=salt-app-backend

# Create SSL certificate (managed by Google)
gcloud compute ssl-certificates create salt-app-cert \
  --domains=salt.app,www.salt.app

# Create HTTPS proxy
gcloud compute target-https-proxies create salt-app-https-proxy \
  --url-map=salt-app-lb \
  --ssl-certificates=salt-app-cert

# Create forwarding rule
gcloud compute forwarding-rules create salt-app-https \
  --global \
  --target-https-proxy=salt-app-https-proxy \
  --address=salt-app-ip \
  --ports=443

# Point DNS to the load balancer IP
# In your DNS provider (e.g., Route 53, Cloudflare):
# A record: salt.app → <FORWARDING_RULE_IP>
```

**Deliverables:**
- [ ] Frontend Cloud Run service deployed
- [ ] Load Balancer configured
- [ ] CDN enabled
- [ ] SSL certificate provisioned
- [ ] Custom domain configured

---

### Phase 7: Scheduled Jobs & Web Scraper (Week 4)

#### 7.1 Deploy Web Scraper as Cloud Run Job

**Update Scraper Dockerfile:**

```dockerfile
# web-scraping/web-scraper.Dockerfile - UPDATED FOR CLOUD RUN JOBS

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
  gcc \
  postgresql-client \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY web-scraping/requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY web-scraping/jobs /app/jobs
COPY web-scraping/utils /app/utils

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# For Cloud Run Jobs, we need to specify the command
# This script will be called by Cloud Scheduler
CMD ["python", "jobs/swell_scraper_hourly.py"]
```

#### 7.2 Create Cloud Run Job

```bash
# Build scraper image
docker build -f web-scraping/web-scraper.Dockerfile \
  -t $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-scraper:latest \
  .

docker push $REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-scraper:latest

# Create Cloud Run Job
gcloud run jobs create salt-scraper-swell \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-scraper:latest \
  --region=$REGION \
  --service-account=salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --vpc-connector=salt-vpc-connector \
  --vpc-egress=private-ranges-only \
  --task-timeout=1800s \
  --set-env-vars="DB_HOST=/cloudsql/$PROJECT_ID:$REGION:salt-postgres-prod" \
  --set-env-vars="DB_NAME=salt_app" \
  --set-env-vars="DB_USER=salt_app_user" \
  --set-env-vars="DB_PORT=5432" \
  --set-env-vars="OPENWEATHER_API_KEY=$OPENWEATHER_API_KEY" \
  --add-cloudsql-instances=$PROJECT_ID:$REGION:salt-postgres-prod \
  --memory=512Mi \
  --cpu=1 \
  --parallelism=1 \
  --task-count=1
```

#### 7.3 Set Up Cloud Scheduler for Job Triggers

```bash
# Create service account for Cloud Scheduler
gcloud iam service-accounts create salt-scheduler-sa \
  --display-name="Salt Scheduler Service Account"

# Grant Cloud Run Job Invoker role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:salt-scheduler-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/run.admin

# Create Cloud Scheduler jobs
# Hourly swell scraper
gcloud scheduler jobs create pubsub salt-scraper-swell-hourly \
  --location=$REGION \
  --schedule="0 * * * *" \
  --message-body='{"jobName":"salt-scraper-swell"}' \
  --topic=cloud-run-jobs

# Create Pub/Sub topic for job triggers
gcloud pubsub topics create cloud-run-jobs

# Alternative: Use HTTP trigger directly
gcloud scheduler jobs create http salt-scraper-swell-hourly \
  --location=$REGION \
  --schedule="0 * * * *" \
  --http-method=POST \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/projects/$PROJECT_ID/jobs/salt-scraper-swell:run" \
  --oidc-service-account-email=salt-scheduler-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --oidc-token-audience="https://$REGION-run.googleapis.com"
```

#### 7.4 Create Pub/Sub for Asynchronous Processing (Optional)

For decoupling the API from long-running tasks:

```bash
# Create Pub/Sub topics
gcloud pubsub topics create salt-media-processing
gcloud pubsub topics create salt-notifications

# Create subscriptions with Cloud Run push
gcloud pubsub subscriptions create salt-media-processor \
  --topic=salt-media-processing \
  --push-endpoint=https://salt-api-<random>.run.app/webhooks/media-process \
  --push-auth-service-account=salt-scheduler-sa@$PROJECT_ID.iam.gserviceaccount.com

# Create Cloud Functions for event processing (alternative)
# Or handle Pub/Sub messages directly in Cloud Run with threading
```

**Deliverables:**
- [ ] Scraper Docker image built
- [ ] Cloud Run Jobs created
- [ ] Cloud Scheduler configured
- [ ] Hourly, daily, weekly jobs scheduled
- [ ] Pub/Sub topics created (for async processing)

---

### Phase 8: Monitoring & Logging (Week 4)

#### 8.1 Configure Cloud Logging

```bash
# Cloud Run automatically sends logs to Cloud Logging
# View logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=salt-api" \
  --limit 50 --format json

# Create log sinks for archival
gcloud logging sinks create salt-logs-archive \
  gs://salt-logs-archive \
  --log-filter='resource.type="cloud_run_revision"'

# Create log-based metrics
gcloud logging metrics create error_rate \
  --log-filter='severity="ERROR"'

gcloud logging metrics create api_latency \
  --log-filter='resource.type="cloud_run_revision"'
```

#### 8.2 Set Up Cloud Monitoring Dashboards

```bash
# Create custom dashboard (example via gcloud)
gcloud monitoring dashboards create \
  --config-from-file=monitoring-dashboard.yaml
```

**Example monitoring-dashboard.yaml:**

```yaml
displayName: Salt App Monitoring
dashboardFilters: []
gridLayout:
  widgets:
  - title: Cloud Run Invocations
    xyChart:
      dataSets:
      - timeSeriesQuery:
          timeSeriesFilter:
            filter: 'resource.type="cloud_run_revision"'
            aggregation:
              alignmentPeriod: 60s
              perSeriesAligner: ALIGN_RATE

  - title: Request Latency (p95)
    xyChart:
      dataSets:
      - timeSeriesQuery:
          timeSeriesFilter:
            filter: 'resource.type="cloud_run_revision"'
            aggregation:
              alignmentPeriod: 60s
              percentileAggregation:
                percentiles: [95]

  - title: Database Connection Pool
    xyChart:
      dataSets:
      - timeSeriesQuery:
          timeSeriesFilter:
            filter: 'resource.type="cloudsql_database"'
```

#### 8.3 Set Up Alerts

```bash
# Create alert policy for high error rate
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Salt API - High Error Rate" \
  --condition-display-name="Error rate > 5%" \
  --condition-threshold-value=0.05 \
  --condition-threshold-duration=300s

# Create alert for Cloud SQL CPU
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Cloud SQL - High CPU" \
  --condition-display-name="CPU > 80%" \
  --condition-threshold-value=0.8
```

#### 8.4 Set Up Tracing (Cloud Trace)

Update API code to use Cloud Trace SDK:

```typescript
// In api/src/index.ts
import { NodeTracerProvider } from '@opentelemetry/node';
import { CloudTraceExporter } from '@google-cloud/opentelemetry-cloud-trace-exporter';
import { registerInstrumentations } from '@opentelemetry/auto-instrumentations-node';

const provider = new NodeTracerProvider();
provider.addSpanProcessor(
  new BatchSpanProcessor(new CloudTraceExporter())
);
provider.register();

registerInstrumentations({
  meterProvider: provider.getMeterProvider(),
});
```

**Deliverables:**
- [ ] Cloud Logging configured
- [ ] Log sinks created for archival
- [ ] Cloud Monitoring dashboard created
- [ ] Alert policies configured
- [ ] Cloud Trace integrated (optional)

---

### Phase 9: Security & Compliance (Week 5)

#### 9.1 Set Up Cloud Armor

```bash
# Create security policy
gcloud compute security-policies create salt-security-policy \
  --description="Security policy for Salt app"

# Add DDoS protection rules
gcloud compute security-policies rules create 100 \
  --security-policy=salt-security-policy \
  --action=allow

# Add rate limiting rule
gcloud compute security-policies rules create 200 \
  --security-policy=salt-security-policy \
  --action=rate-based-ban \
  --rate-limit-options=enforce-on-key=IP,ban-duration-sec=600 \
  --ban-threshold-count=100 \
  --ban-threshold-interval-sec=60

# Attach to load balancer
gcloud compute backend-services update salt-app-backend \
  --global \
  --security-policy=salt-security-policy
```

#### 9.2 Configure IAM Policies

```bash
# Create custom role for developers
gcloud iam roles create salt-developer \
  --project=$PROJECT_ID \
  --title="Salt Developer" \
  --description="Can deploy and manage Salt services" \
  --permissions=run.services.update,run.services.get,logging.logEntries.create

# Grant roles to team members
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=user:dev@example.com \
  --role=projects/$PROJECT_ID/roles/salt-developer

# Create audit logging
gcloud logging sinks create salt-audit-logs \
  gs://salt-audit-logs \
  --log-filter='protoPayload.methodName=~"storage\..*"'
```

#### 9.3 Enable VPC Service Controls (Optional)

```bash
# Create security perimeter
gcloud access-context-manager perimeters create salt-perimeter \
  --resources=projects/$PROJECT_ID \
  --restricted-services=run.googleapis.com,sql.googleapis.com,storage.googleapis.com
```

#### 9.4 Secrets Management

```bash
# All secrets should be in Secrets Manager
gcloud secrets create mapbox-token --data-file=- << EOF
$MAPBOX_TOKEN
EOF

gcloud secrets create sendgrid-api-key --data-file=- << EOF
$SENDGRID_API_KEY
EOF

# Grant access to Cloud Run
gcloud secrets add-iam-policy-binding mapbox-token \
  --member=serviceAccount:salt-api-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

**Deliverables:**
- [ ] Cloud Armor policies configured
- [ ] IAM roles and policies set
- [ ] Audit logging enabled
- [ ] All secrets in Secrets Manager
- [ ] VPC Service Controls configured (optional)

---

### Phase 10: Testing & Validation (Week 5)

#### 10.1 Load Testing

```bash
# Use Cloud Load Testing (or Apache JMeter/Locust)
# Generate typical load profile
gcloud compute instances create load-tester \
  --image-family=debian-11 \
  --image-project=debian-cloud

# Install testing tools
apt-get install -y apache2-utils

# Run load test
ab -n 10000 -c 100 https://api.salt.app/health
```

#### 10.2 Smoke Testing

```bash
# Test API endpoints
curl -X GET https://api.salt.app/health

# Test authentication
curl -X POST https://api.salt.app/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass"}'

# Test file upload
curl -X POST https://api.salt.app/upload/session-media \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -F "file=@test-image.jpg"
```

#### 10.3 Database Validation

```bash
# Check data integrity
psql -h salt-postgres-prod -U postgres -d salt_app << EOF
SELECT COUNT(*) FROM auth.users;
SELECT COUNT(*) FROM public.sessions;
SELECT COUNT(*) FROM public.boards;
EOF

# Verify foreign key relationships
psql -h salt-postgres-prod -U postgres -d salt_app << EOF
\d+ public.sessions
EOF
```

#### 10.4 Performance Benchmarks

- API response time: Target < 500ms
- Frontend load time: Target < 2s
- Database query time: Target < 100ms
- CDN cache hit rate: Target > 90%

**Deliverables:**
- [ ] Load tests completed
- [ ] Smoke tests passed
- [ ] Data integrity verified
- [ ] Performance benchmarks met
- [ ] Production readiness confirmed

---

### Phase 11: Migration & Cutover (Week 6)

#### 11.1 Parallel Running (Shadow Mode)

Run both old and new systems simultaneously:

```bash
# On old system, configure replication to Cloud SQL
# Use a streaming replication or event trigger mechanism

# On new system, validate all data is correct
# Run same operations on both systems, compare results

# For 1-2 weeks, both systems should be running
```

#### 11.2 Database Cutover

```bash
# Before cutover, ensure all data is synced
# Perform final backup of old database
pg_dump -h old-db-host -U postgres -d salt_app > final_backup.sql

# Switch application to use new database
# Update API connection strings to Cloud SQL

# Monitor for issues, keep old database as backup for 30 days
```

#### 11.3 DNS Cutover

```bash
# Update DNS to point to Google Cloud Load Balancer
# In your DNS provider:
# A record: salt.app → <LOAD_BALANCER_IP>

# Test with local DNS override first
echo "LOAD_BALANCER_IP salt.app" >> /etc/hosts
```

#### 11.4 Traffic Monitoring

```bash
# Monitor all metrics during and after cutover
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit=100 --format=json | jq .

# Watch Cloud Monitoring dashboard
# Check error rates, latency, database connections
```

**Deliverables:**
- [ ] Parallel running verified
- [ ] Data sync confirmed
- [ ] Cutover completed
- [ ] Traffic monitoring active
- [ ] Rollback plan ready (if needed)

---

### Phase 12: Optimization & Cleanup (Week 6-7)

#### 12.1 Performance Optimization

```bash
# Analyze query performance
gcloud sql operations list \
  --instance=salt-postgres-prod \
  --filter='status!=DONE'

# Review Cloud Trace data
# Identify slow endpoints and optimize

# Enable query insights (Cloud SQL)
gcloud sql instances patch salt-postgres-prod \
  --insights-config-enabled \
  --insights-config-query-string-length=1024 \
  --insights-config-record-application-tags
```

#### 12.2 Cost Optimization

```bash
# Review resource utilization
# Right-size Cloud Run instances (reduce memory/CPU if possible)
# Set appropriate min/max instances

gcloud run services update salt-api \
  --min-instances=1 \
  --max-instances=30 \
  --region=$REGION

# Set up budget alerts
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="Salt App Budget" \
  --budget-amount=1000 \
  --threshold-rule=percent=50,percent=90,percent=100
```

#### 12.3 Decommission Old Infrastructure

```bash
# Only after several weeks of successful operation:
# Shut down old Kubernetes cluster
# Delete old PostgreSQL instance (keep backup)
# Cancel old services

# Keep backups for compliance (1+ year)
```

#### 12.4 Documentation

```bash
# Update internal documentation
# Create runbooks for common operations:
# - How to scale services
# - How to rollback
# - Incident response procedures
# - Disaster recovery procedures
```

**Deliverables:**
- [ ] Performance optimized
- [ ] Cost optimized
- [ ] Old infrastructure decommissioned
- [ ] Documentation updated
- [ ] Team trained on new system

---

## Service-by-Service Migration Details

### 1. API Backend

**Current State:** Express.js running on K3s with PostgreSQL  
**New State:** Cloud Run container with Cloud SQL

**Changes Required:**
- [x] Database connection: Update to Cloud SQL Unix socket
- [x] Environment variables: Configure via Cloud Run
- [x] Secrets: Store in Secrets Manager
- [x] Health checks: Already implemented
- [ ] Logging: Switch to Cloud Logging (automatic)
- [ ] Monitoring: Add OpenTelemetry SDK (optional)

**New Connection String Format:**
```typescript
// Old:
const db = new Pool({
  host: process.env.DB_HOST,
  port: 5432,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
});

// New (Cloud SQL Proxy Unix socket):
const db = new Pool({
  socketPath: `/cloudsql/${PROJECT_ID}:${REGION}:salt-postgres-prod`,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
});

// Or use environment variables that Cloud Run sets automatically:
const db = new Pool({
  host: '/cloudsql/' + process.env.INSTANCE_CONNECTION_NAME,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
});
```

### 2. Frontend Application

**Current State:** React + Nginx on K3s  
**New State:** Cloud Run container with Cloud CDN + Load Balancer

**Changes Required:**
- [x] Build process: Update Dockerfile (already done)
- [x] Environment variables: Set at build time
- [x] Serving: Use Nginx or simple HTTP server
- [x] CORS: Configure for new API domain
- [x] CDN: Integrated via Load Balancer

**Build Environment Variables:**
```env
VITE_API_URL=https://api.salt.app
VITE_MINIO_URL=https://media.salt.app
VITE_MAPBOX_TOKEN=<token>
```

### 3. Web Scraper

**Current State:** Python cron jobs on K3s  
**New State:** Cloud Run Jobs triggered by Cloud Scheduler

**Changes Required:**
- [x] Dockerfile update for Cloud Run Jobs
- [x] Database connection: Use Cloud SQL
- [ ] MinIO integration: Switch to Cloud Storage
- [x] Logging: Use Cloud Logging
- [x] Scheduling: Use Cloud Scheduler

**MinIO to Cloud Storage Migration:**
```python
# Old (MinIO):
from minio import Minio

minio_client = Minio(
  os.getenv('MINIO_ENDPOINT'),
  access_key=os.getenv('MINIO_ACCESS_KEY'),
  secret_key=os.getenv('MINIO_SECRET_KEY')
)

minio_client.fput_object(
  'argo-logs',
  'scraper-output.json',
  '/tmp/output.json'
)

# New (Cloud Storage):
from google.cloud import storage

storage_client = storage.Client()
bucket = storage_client.bucket('salt-logs')
blob = bucket.blob('scraper-output.json')
blob.upload_from_filename('/tmp/output.json')
```

### 4. Database (PostgreSQL)

**Current State:** PostgreSQL on Raspberry Pi (bare metal)  
**New State:** Cloud SQL Managed Database

**Key Differences:**
- Automatic backups with point-in-time recovery
- Automatic failover (HA configuration)
- Automatic patching
- Better performance monitoring
- Connection pooling built-in
- Automatic scaling of storage

**Migration Path:**
1. Create Cloud SQL instance (Week 2)
2. Use DMS for continuous replication (optional)
3. Test with production-like load
4. Cut over traffic during low-traffic window
5. Verify data integrity
6. Keep old database as backup for 30 days

### 5. Object Storage (MinIO → Cloud Storage)

**Current State:** MinIO S3-compatible storage  
**New State:** Google Cloud Storage with CDN

**Bucket Mapping:**
```
session-media  → salt-media-prod/sessions/
avatars        → salt-media-prod/avatars/
board-photos   → salt-media-prod/boards/
argo-logs      → salt-logs-archive/
```

**Migration Script:**
```bash
# Copy MinIO data to Cloud Storage
gsutil -m cp -r gs://minio-backup/* gs://salt-media-prod/

# Update API to use Cloud Storage
# No changes needed if using S3 API compatibility
# Or update to native GCS SDK
```

**Cost Comparison:**
| Service | MinIO (Self-hosted) | Cloud Storage |
|---------|-------------------|---------------|
| Storage | $10/month (shared HW) | $0.020/GB/month |
| Bandwidth (1TB/mo) | Included | $0.12/GB |
| Egress CDN | Not included | $0.085/GB |
| **Total (1TB)** | ~$10 | ~$200 |

*Note: Cloud Storage much cheaper for egress-heavy workloads*

---

## Cost Estimation

### Monthly Costs Breakdown

#### Compute
| Service | Pricing | Est. Monthly |
|---------|---------|--------------|
| Cloud Run API | $0.40/GB-hour (512MB × 30 min/day) | $180 |
| Cloud Run Frontend | $0.40/GB-hour (256MB × 30 min/day) | $90 |
| Cloud Run Jobs | $0.40/GB-hour (512MB × 1 hour/day) | $12 |
| **Subtotal** | | **$282** |

#### Database
| Service | Pricing | Est. Monthly |
|---------|---------|--------------|
| Cloud SQL (db-custom-2-8GB) | $0.51/hour | $365 |
| Storage (100GB) | $0.20/GB | $20 |
| Backups (100GB) | $0.026/GB | $2.60 |
| **Subtotal** | | **$388** |

#### Storage
| Service | Pricing | Est. Monthly |
|---------|---------|--------------|
| Cloud Storage (100GB) | $0.020/GB | $2 |
| Egress (500GB) | $0.12/GB | $60 |
| CDN (500GB) | $0.085/GB | $42.50 |
| **Subtotal** | | **$105** |

#### Networking
| Service | Pricing | Est. Monthly |
|---------|---------|--------------|
| Load Balancer | $0.025/hour + $0.006/GB | $18 + $3 |
| VPC Connector | $0.025/hour + traffic | $18 |
| Cloud Scheduler | $0.10/job | $1 |
| **Subtotal** | | **$40** |

#### Monitoring (included)
| Service | Pricing | Est. Monthly |
|---------|---------|--------------|
| Cloud Logging (5GB/mo) | Free tier | $0 |
| Cloud Monitoring | Free tier | $0 |
| Cloud Trace | $5/million spans | $5 |

#### **Total Estimated Monthly Cost: $820**

**Compared to Current Self-Hosted:**
- Hardware lease: ~$200/month
- Power/cooling: ~$50/month
- Internet: ~$100/month
- Labor (maintenance): ~$1000/month estimate
- **Total: ~$1,350/month**

**GCP advantages:**
- 40% cost reduction
- Zero ops/maintenance
- Automatic scaling
- Built-in security
- Global CDN

---

## Rollback Plan

### Immediate Rollback (First 24 Hours)

If critical issues occur during cutover:

```bash
# Point DNS back to old system
# Update DNS A record to old server IP

# Verify all traffic is routed correctly
curl -I https://salt.app

# Monitor error rates should drop immediately
```

### Gradual Rollback (First Week)

If issues are identified post-migration:

```bash
# Use Cloud Load Balancer to split traffic
# 10% to new system, 90% to old system
# Monitor metrics

# Gradually increase new system traffic
# 25% → 50% → 75% → 100%
```

### Full Recovery (If Needed)

```bash
# Keep old database running for 30 days post-migration
# If data corruption detected, restore from backup:

pg_restore -h old-db-host -d salt_app final_backup.sql

# Restart old K3s cluster if needed
# Roll back API and frontend to old Docker images
```

**Key: Don't delete anything for at least 30 days**

---

## Risk Assessment & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Data migration failure | Low | Critical | DMS testing, backup verification |
| Performance issues | Medium | High | Load testing, Cloud SQL tuning |
| Cost overruns | Medium | Medium | Budget alerts, resource optimization |
| DNS propagation delays | Low | Medium | DNS pre-staging, TTL reduction |
| Cloud SQL unavailability | Very Low | Critical | HA configuration, automatic failover |
| API compatibility issues | Low | High | Thorough testing, gradual migration |

---

## Timeline

### Week 1-2: Foundation
- [ ] GCP project setup
- [ ] VPC and networking
- [ ] Cloud SQL instance
- [ ] Database migration

### Week 2-3: Infrastructure
- [ ] Cloud Storage setup
- [ ] Artifact Registry
- [ ] Docker images built
- [ ] Secrets Manager

### Week 3-4: Deployment
- [ ] API deployment
- [ ] Frontend deployment
- [ ] Load Balancer setup
- [ ] Job scheduler setup

### Week 4-5: Operations
- [ ] Monitoring configured
- [ ] Security hardened
- [ ] Testing completed
- [ ] Load testing

### Week 5-6: Cutover
- [ ] Parallel running
- [ ] DNS cutover
- [ ] Traffic monitoring
- [ ] Incident response

### Week 6-7: Optimization
- [ ] Performance tuning
- [ ] Cost optimization
- [ ] Old system decommission
- [ ] Documentation

---

## Success Criteria

✅ All services running on GCP  
✅ Zero data loss  
✅ Performance equal or better  
✅ 99.9% uptime  
✅ All tests passing  
✅ Cost within budget  
✅ Security policies enforced  
✅ Team trained on new platform  

---

## Post-Migration Operations

### Ongoing Maintenance

**Daily:**
- Monitor Cloud Logging for errors
- Check Cloud Monitoring dashboards

**Weekly:**
- Review cost trends
- Analyze performance metrics
- Update documentation

**Monthly:**
- Right-size resources
- Test disaster recovery
- Review security logs
- Update runbooks

### Disaster Recovery Procedures

**Database Recovery:**
```bash
# Restore from automatic backup (PITR)
gcloud sql backups create salt-backup \
  --instance=salt-postgres-prod

# Restore to point-in-time
gcloud sql backups restore <BACKUP_ID> \
  --backup-instance=salt-postgres-prod
```

**Service Recovery:**
```bash
# Redeploy from image
gcloud run deploy salt-api \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/salt-docker-repo/salt-api:latest \
  --region=$REGION

# Automatic rollback available via Cloud Run revisions
```

---

## Conclusion

This migration plan transforms Salt from a self-managed Kubernetes cluster to a serverless, globally-scalable platform on Google Cloud. The phased approach minimizes risk while the parallel running period ensures data integrity and system stability.

**Key Takeaways:**
1. **Serverless = Less Operations** - No infrastructure to manage
2. **Better Performance** - Global CDN, managed databases
3. **Cost Efficient** - 40% reduction from self-hosted
4. **Scalability** - Handles growth automatically
5. **Security** - Enterprise-grade built-in

For questions or clarifications, refer to the GCP documentation or contact your cloud architect.
