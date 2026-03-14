# Infrastructure Architecture Skill

You are an expert in the GiftBee infrastructure. Apply this knowledge when implementing
DevOps tasks, Docker changes, CI/CD pipelines, OpenTofu modules, or any infrastructure work.

---

## Infrastructure Overview

GiftBee runs on two environments:

| Environment | Infrastructure |
|-------------|---------------|
| **Local development** | Docker Compose (`local-infra/docker-compose.yml`) |
| **Production (wallet-service)** | AWS — Bref/Lambda + RDS + SQS + S3 + CloudFront |
| **Mason agents** | AWS Bedrock AgentCore + DynamoDB + API Gateway |

---

## Local Development Infrastructure (`local-infra`)

### Docker Networks

Three isolated networks — services only talk to services on the same network:

```yaml
networks:
  giftbee_frontend_network:    # store-front ↔ nginx
    driver: bridge
  giftbee_backend_network:     # wallet-service ↔ redis ↔ mysql ↔ mailpit ↔ pim
    driver: bridge
  giftbee_admin_portal_network: # admin-portal ↔ nginx
    driver: bridge
```

**Which service sits on which network:**

| Service | Networks |
|---------|----------|
| nginx | frontend + backend + admin_portal |
| store-front | frontend |
| admin-portal | admin_portal |
| wallet-service | backend |
| pim | backend |
| mysql | backend |
| redis | backend |
| mailpit | backend |
| phpmyadmin | backend |
| redis_insight | backend |

### Service Map

```yaml
services:
  mailpit:            # SMTP testing — http://localhost:8025
    image: axllent/mailpit
    ports: [1025:1025, 8025:8025]  # SMTP + web UI

  redis:              # Cache + queue broker
    image: redis:alpine
    ports: [6379:6379]

  redis_insight:      # Redis GUI — http://localhost:5540
    image: redis/redisinsight
    ports: [5540:5540]

  mysql:              # Primary database (custom image with multiple DBs)
    build: ./mysql
    ports: [3306:3306]

  nginx:              # Reverse proxy — routes traffic to services
    build: ./nginx
    ports: [80:80, 443:443]

  phpmyadmin:         # MySQL GUI — http://localhost:8090
    image: phpmyadmin
    ports: [8090:80]

  # Application services (defined in local-infra with volume mounts to ../repos)
  store-front:        # http://localhost:3000
  admin-portal:       # http://localhost:3001
  wallet-service:     # http://localhost:8000
  pim:                # http://localhost:8080
```

### Environment Variables for Local Dev

Every application reads from `.env` in its repo root. The `local-infra` repo provides
`.env.example` files for each service. Key variables:

```bash
# wallet-service .env
APP_ENV=local
APP_KEY=base64:...
DB_CONNECTION=mysql
DB_HOST=mysql              # Docker service name, not localhost
DB_PORT=3306
REDIS_HOST=redis           # Docker service name
REDIS_PORT=6379
QUEUE_CONNECTION=sync      # Use 'sqs' in production, 'sync' locally
MAIL_HOST=mailpit          # Mailpit catches all outgoing email locally
MAIL_PORT=1025

# store-front .env.local
NEXT_APP_API_BASE_URL=http://localhost:8000
NEXT_APP_KEY=local-jwt-secret
NEXT_AUTH_PASSWORD_CLIENT_ID=2
NEXT_AUTH_PASSWORD_CLIENT_SECRET=xxx
```

### Nginx Configuration

Nginx acts as a reverse proxy. Config files are in `local-infra/nginx/`:

```nginx
# nginx/sites/store-front.conf
server {
    listen 80;
    server_name store.giftbee.local;

    location / {
        proxy_pass http://store-front:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# nginx/sites/wallet-service.conf
server {
    listen 80;
    server_name api.giftbee.local;

    location / {
        proxy_pass http://wallet-service:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Adding a New Service to Docker Compose

```yaml
# 1. Add to local-infra/docker-compose.yml
services:
  notification-service:
    build:
      context: ../notification-service
      dockerfile: Dockerfile
    ports:
      - "3002:3002"
    networks:
      - giftbee_backend_network
    depends_on:
      - redis
      - mysql
    environment:
      - REDIS_HOST=redis
      - DB_HOST=mysql
    volumes:
      - ../notification-service:/app  # hot reload in development

# 2. Add Nginx config: local-infra/nginx/sites/notification-service.conf
# 3. Add .env.example to the new service repo
# 4. Document the new port in README.md
```

---

## Production Infrastructure (wallet-service on AWS)

### Serverless with Bref + AWS Lambda

`wallet-service` deploys to **AWS Lambda** using the [Bref](https://bref.sh/) framework.
This means:
- No persistent filesystem writes — use S3 for storage
- No long-running processes — use SQS for async work
- Cold starts — keep `bootstrap/app.php` lean
- Max execution time: 29s for HTTP, 15min for CLI/queue workers

```yaml
# serverless.yml (wallet-service)
service: giftbee-wallet-service

provider:
  name: aws
  region: ap-southeast-2
  runtime: provided.al2023

functions:
  api:
    handler: Bref\LaravelBridge\Http\OctaneHandler
    layers:
      - ${bref:layer.php-83-fpm}
    events:
      - httpApi: '*'

  artisan:
    handler: Bref\LaravelBridge\Console\ArtisanHandler
    layers:
      - ${bref:layer.php-83}
    events:
      - schedule:
          rate: rate(5 minutes)
          input: '"schedule:run"'

  queue-worker:
    handler: Bref\LaravelBridge\Queue\QueueHandler
    layers:
      - ${bref:layer.php-83}
    events:
      - sqs:
          arn: !GetAtt OrdersQueue.Arn
          batchSize: 10
```

### AWS Services Used (wallet-service)

| Service | Purpose |
|---------|---------|
| AWS Lambda | API execution (Bref/OctaneHandler) |
| API Gateway | HTTPS endpoint → Lambda routing |
| RDS MySQL | Primary database |
| ElastiCache Redis | Cache + session storage |
| SQS | Job queues (orders, emails, notifications) |
| S3 | File storage (receipts, exports, images) |
| CloudFront | CDN for static assets + S3 distribution |
| Secrets Manager | `.env` variables (loaded at Lambda cold start) |
| CloudWatch | Logs + alarms |

### File Storage (S3)

```php
// Never write to local filesystem in Lambda
// ❌ file_put_contents('/tmp/report.csv', $data);  // unreliable in Lambda
// ✅
Storage::disk('s3')->put("reports/{$date}/orders.csv", $csvContent);

// Presigned URL for browser downloads (15 min expiry)
$url = Storage::disk('s3')->temporaryUrl("reports/{$date}/orders.csv", now()->addMinutes(15));
```

### Queue Configuration

```php
// .env (production)
QUEUE_CONNECTION=sqs
AWS_SQS_QUEUE_URL=https://sqs.ap-southeast-2.amazonaws.com/123456789/giftbee-orders
SQS_PREFIX=https://sqs.ap-southeast-2.amazonaws.com/123456789

// Separate queues by priority/type
ProcessGiftCardOrder::dispatch($order)->onQueue('orders');
SendGiftCardEmail::dispatch($order)->onQueue('emails');
GeneratePDFReport::dispatch($params)->onQueue('reports');
```

---

## Mason Agent Infrastructure (AWS Bedrock)

The `mason` orchestration system runs on AWS Bedrock AgentCore with supporting services.

### Architecture Diagram

```
Jira Webhook
     │
     ▼
API Gateway (/webhook) ──────────────────────┐
                                              ▼
                                   Bedrock AgentCore Runtime
                                   ┌────────────────────────┐
                                   │  Orchestrator (Opus)   │
                                   │  ┌──────────────────┐  │
                                   │  │  Worker (Sonnet) │  │
                                   │  │  Worker (Sonnet) │  │
                                   │  └──────────────────┘  │
                                   └────────┬───────────────┘
                                            │
                     ┌──────────────────────┼─────────────────────┐
                     ▼                      ▼                     ▼
              DynamoDB Memory          CloudWatch Logs       Secrets Manager
          (session/episodic/semantic)   (structured logs)    (API keys, tokens)
```

### OpenTofu Modules (`infra/tofu/modules/`)

IaC is managed with **OpenTofu** (open-source Terraform fork). Four modules:

```
infra/tofu/
  modules/
    gateway/          # API Gateway for Jira webhook ingestion
    memory/           # DynamoDB tables for agent memory
    observability/    # CloudWatch log groups + alarms
    runtime/          # IAM roles, secrets, Bedrock config
  envs/
    staging/          # terraform.tfvars for staging
    production/       # terraform.tfvars for production
  main.tf             # Module composition
  variables.tf        # Input variables
  outputs.tf          # Output values
  versions.tf         # Provider versions
```

#### Memory Module (DynamoDB)

Three tables for agent memory:

```hcl
# Session memory — active task context (TTL: 24h)
aws_dynamodb_table "session_memory":
  hash_key  = "session_id"
  range_key = "timestamp"
  ttl       = enabled

# Episodic memory — past task outcomes (how bugs were fixed, etc.)
aws_dynamodb_table "episodic_memory":
  hash_key  = "agent_id"
  range_key = "episode_id"

# Semantic memory — long-term coding preferences and architectural rules
aws_dynamodb_table "semantic_memory":
  hash_key  = "key"
```

#### Gateway Module (API Gateway)

```hcl
# Webhook endpoint for Jira events
aws_api_gateway_rest_api "webhook":
  POST /webhook → Lambda (AgentCore trigger)

# Response: 202 Accepted (async processing)
```

#### Runtime Module (IAM + Secrets)

```hcl
# IAM roles for Bedrock model invocation
aws_iam_role "orchestrator":  # Opus model invocation
aws_iam_role "worker":        # Sonnet model invocation

# Permissions:
#  - bedrock:InvokeModel (anthropic.* models)
#  - dynamodb:GetItem / PutItem / UpdateItem (memory tables)
#  - secretsmanager:GetSecretValue
#  - logs:CreateLogStream / PutLogEvents
```

#### Observability Module (CloudWatch)

```hcl
# Log groups (30-day retention)
aws_cloudwatch_log_group "/mason/orchestrator"
aws_cloudwatch_log_group "/mason/worker"
aws_cloudwatch_log_group "/mason/webhook"

# Cost alarm — alert if Bedrock invocations exceed threshold
aws_cloudwatch_metric_alarm "bedrock_cost":
  threshold = var.daily_cost_alarm_threshold  # default: 10,000 invocations
  alarm_actions = [aws_sns_topic.alerts.arn]
```

### Running OpenTofu

```bash
# Set up
cd infra/tofu
tofu init

# Plan changes
tofu plan -var-file=envs/staging/terraform.tfvars

# Apply changes
tofu apply -var-file=envs/staging/terraform.tfvars

# Or use the deploy script
./scripts/deploy.sh staging plan
./scripts/deploy.sh staging apply
./scripts/deploy.sh production apply
```

---

## CI/CD with Bitbucket Pipelines

Each repo has a `bitbucket-pipelines.yml`. The pipeline runs on every push and deploys on merge to `main`.

### Pipeline Stages

```yaml
# bitbucket-pipelines.yml (wallet-service)
pipelines:
  default:
    - step:
        name: Test
        image: php:8.3-cli
        script:
          - composer install --no-interaction
          - vendor/bin/phpstan analyse app/ --level=8
          - php artisan test --parallel

  branches:
    main:
      - step:
          name: Test
          # ... same as above
      - step:
          name: Deploy to Staging
          deployment: staging
          script:
            - npm install -g serverless
            - serverless deploy --stage staging
      - step:
          name: Deploy to Production
          deployment: production
          trigger: manual        # Requires human approval
          script:
            - serverless deploy --stage production
```

### Pipeline for Frontend (store-front / admin-portal)

```yaml
# bitbucket-pipelines.yml (store-front)
pipelines:
  default:
    - step:
        name: Lint + Test
        image: node:20
        script:
          - npm ci
          - npm run lint
          - npm run test

  branches:
    main:
      - step:
          name: Build + Deploy
          image: node:20
          script:
            - npm ci
            - npm run build
            - aws s3 sync .next/static s3://${S3_BUCKET}/_next/static
            # Or deploy to Amplify / Vercel
```

---

## Secret Management

| Environment | Where secrets live |
|-------------|-------------------|
| Local | `.env` file in repo root (not committed) — copy from `.env.example` |
| Staging/Production | AWS Secrets Manager — loaded at Lambda cold start via Bref |

```php
// Bref loads secrets from Secrets Manager at startup
// config/app.php — APP_KEY is fetched from Secrets Manager ARN
// Set in serverless.yml:
// APP_KEY: ${ssm:/giftbee/production/app-key}
// Or Secrets Manager:
// APP_KEY: arn:aws:secretsmanager:ap-southeast-2:123456789:secret:giftbee/app-key
```

### Mason Secrets

```python
# In Python — read from environment (set by Bedrock AgentCore / Secrets Manager)
import os

JIRA_API_TOKEN   = os.environ["JIRA_API_TOKEN"]
GITHUB_TOKEN     = os.environ["GITHUB_TOKEN"]
TEAMS_WEBHOOK    = os.environ["TEAMS_WEBHOOK_URL"]
FIGMA_TOKEN      = os.environ["FIGMA_ACCESS_TOKEN"]
```

---

## Observability and Logging

### Structured Logging

All services emit structured JSON logs to CloudWatch:

```python
# mason — Python structured logging
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
            "task_id": getattr(record, "task_id", None),
        })

# Usage
logger.info("Task started", extra={"task_id": task.id})
logger.error("MCP call failed", extra={"task_id": task.id, "service": "jira"})
```

```php
// wallet-service — Laravel logging (daily channel → CloudWatch in production)
Log::channel('cloudwatch')->info('Order created', [
    'order_id' => $order->id,
    'user_id'  => $order->user_id,
    'amount'   => $order->amount,
]);
```

### Alarms

| Alarm | Threshold | Action |
|-------|-----------|--------|
| Bedrock invocation count | >10,000/day | SNS → email/Teams |
| Lambda error rate | >5% | SNS → email/Teams |
| SQS queue depth (orders) | >1000 | SNS → email/Teams |
| RDS connections | >80% max | SNS → email/Teams |

---

## Security Conventions

- **IAM least privilege** — each Lambda function gets only the permissions it needs
- **No hardcoded credentials** — all secrets in AWS Secrets Manager or `.env`
- **VPC** — RDS and ElastiCache are in a private VPC subnet, not publicly accessible
- **HTTPS everywhere** — API Gateway enforces TLS; no HTTP in production
- **CORS** — API Gateway allows only `store-front` and `admin-portal` domains
- **Laravel CSP** — `spatie/laravel-csp` enforces Content Security Policy headers
- **Rate limiting** — API Gateway throttle + Laravel `throttle` middleware on auth endpoints

---

## Common Infrastructure Tasks

### Restart a local service

```bash
cd local-infra
docker compose restart wallet-service
docker compose logs -f wallet-service
```

### Run Laravel migrations in local Docker

```bash
cd local-infra
docker compose exec wallet-service php artisan migrate
docker compose exec wallet-service php artisan db:seed
```

### Open a shell in a container

```bash
docker compose exec wallet-service bash
docker compose exec store-front sh
```

### Reset local database

```bash
cd local-infra
docker compose exec wallet-service php artisan migrate:fresh --seed
```

### Deploy to staging

```bash
# mason infra
./scripts/deploy.sh staging apply

# wallet-service (from its own repo)
serverless deploy --stage staging
```
