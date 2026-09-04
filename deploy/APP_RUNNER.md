# AWS App Runner deployment

Deploys the container image already published to your private ECR repository by
the Jenkins pipeline. The Hugging Face token is stored in AWS Secrets Manager
and injected at runtime, never pasted into the console as plaintext.

Region throughout: `us-east-1`. Substitute your own account ID and bucket name.

---

## 1. Store the token in Secrets Manager

A plaintext secret (not key/value) keeps the App Runner reference simple: the
whole value becomes the environment variable.

```bash
aws secretsmanager create-secret \
  --name medical-rag/hf-token \
  --description "Hugging Face Inference API token for Medical AI RAG System" \
  --secret-string "hf_your_actual_token_here" \
  --region us-east-1
```

Note the returned `ARN` — you need it twice below.

To retrieve it later:

```bash
aws secretsmanager describe-secret --secret-id medical-rag/hf-token \
  --region us-east-1 --query ARN --output text
```

> Rotating the token later is `aws secretsmanager update-secret --secret-id
> medical-rag/hf-token --secret-string "hf_new"` followed by a new deployment.
> No image rebuild, no code change. That separation is the point.

---

## 2. Create the instance role

App Runner assumes this role *inside* the running container so it can read the
secret. It is distinct from the ECR access role in step 3, which is used at
deploy time to pull the image. Two roles, two purposes, two trust policies.

```bash
cat > /tmp/apprunner-trust.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "tasks.apprunner.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
JSON

aws iam create-role \
  --role-name MedicalRagAppRunnerInstanceRole \
  --assume-role-policy-document file:///tmp/apprunner-trust.json
```

Grant it read access to that one secret only — not `secretsmanager:*`:

```bash
SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id medical-rag/hf-token --region us-east-1 \
  --query ARN --output text)

cat > /tmp/secret-policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "${SECRET_ARN}"
  }]
}
JSON

aws iam put-role-policy \
  --role-name MedicalRagAppRunnerInstanceRole \
  --policy-name ReadHuggingFaceToken \
  --policy-document file:///tmp/secret-policy.json
```

---

## 3. Create the service (console)

The console creates the ECR access role for you, which is why this step is not
scripted. Hand-writing that trust policy is easy to get subtly wrong.

**App Runner → Create service**

**Source**
- Repository type: *Container registry*
- Provider: *Amazon ECR*
- Container image URI: **Browse** → `medical-ai-rag-system` → tag `latest`
- Deployment trigger: **Manual**
  (Jenkins triggers deployments explicitly; automatic would deploy on every
  push to `:latest`, bypassing the pipeline's gates.)
- ECR access role: *Create new service role*

**Service settings**
- Service name: `medical-ai-rag-system`
- Virtual CPU: **1 vCPU**, Memory: **2 GB**
- Port: **8080**

**Environment variables** — add four plaintext, one from the secret:

| Name | Source | Value |
|---|---|---|
| `ENVIRONMENT` | Plain text | `production` |
| `LOG_LEVEL` | Plain text | `INFO` |
| `LLM_REPO_ID` | Plain text | `meta-llama/Llama-3.1-8B-Instruct` |
| `LLM_PROVIDER` | Plain text | `novita` |
| `HF_TOKEN` | **Secrets Manager** | the secret ARN from step 1 |

**Instance role**: `MedicalRagAppRunnerInstanceRole`

**Health check** (expand *Configure health check*)
- Protocol: **HTTP**  ← not the TCP default
- Path: `/health`
- Interval: `20` seconds
- Timeout: `10` seconds
- Healthy threshold: `1`
- Unhealthy threshold: `5`

> HTTP over TCP matters. A TCP check passes as soon as the port is open, which
> happens before the FAISS index and embedding model finish loading. The
> `/health` endpoint returns 503 until both are ready, so App Runner waits for
> genuine readiness instead of mere reachability.
>
> The thresholds allow 100 seconds before the service is declared unhealthy.
> Cold start loads a 4,932-vector index plus a ~90 MB embedding model, both
> baked into the image, so this is comfortable but not tight.

**Auto scaling**: the default (min 1 instance) is fine. Setting min to 1 means
one instance always provisioned — that is what you are paying for at idle.

Create, then wait 5–10 minutes for the first deployment.

---

## 4. Verify

```bash
SERVICE_URL=$(aws apprunner list-services --region us-east-1 \
  --query "ServiceSummaryList[?ServiceName=='medical-ai-rag-system'].ServiceUrl" \
  --output text)

curl "https://${SERVICE_URL}/health"
```

Expect:

```json
{"status":"ok","retriever_ready":true,"llm_ready":true,"vectors":4932,
 "environment":"production", ...}
```

Two things to confirm: `"environment":"production"` proves the env var reached
the container, and `"llm_ready":true` proves the Secrets Manager injection
worked. If `llm_ready` is false, the token did not arrive — check the instance
role and the secret ARN.

Then open `https://${SERVICE_URL}/` and ask a question.

---

## 5. Let Jenkins deploy

Once the service exists, re-run the pipeline with **DEPLOY** ticked. The
`Deploy to App Runner` stage looks up the service by name and calls
`start-deployment`, which pulls the new `:latest` image.

The stage fails with a clear message if no service is found, which is why it
is skipped by default until this manual setup is done.

---

## 6. Controlling cost

App Runner bills hourly, not monthly. Charges are for **provisioned memory**
continuously plus **vCPU only while serving requests**. At 1 vCPU / 2 GB an
idle service runs roughly **$5–8/month**; check the current
[pricing page](https://aws.amazon.com/apprunner/pricing/) for exact rates.

**Between demos — pause:**

```bash
SERVICE_ARN=$(aws apprunner list-services --region us-east-1 \
  --query "ServiceSummaryList[?ServiceName=='medical-ai-rag-system'].ServiceArn" \
  --output text)

aws apprunner pause-service --service-arn "$SERVICE_ARN" --region us-east-1
```

Resuming takes a few minutes:

```bash
aws apprunner resume-service --service-arn "$SERVICE_ARN" --region us-east-1
```

**When finished entirely — delete:**

```bash
aws apprunner delete-service --service-arn "$SERVICE_ARN" --region us-east-1
```

Deleting the service does not remove the ECR images, the S3 artifact, or the
secret. Those cost cents per month, but to clear them fully:

```bash
aws ecr delete-repository --repository-name medical-ai-rag-system \
  --force --region us-east-1
aws s3 rm s3://YOUR-BUCKET --recursive
aws secretsmanager delete-secret --secret-id medical-rag/hf-token \
  --force-delete-without-recovery --region us-east-1
```

**Set a billing alarm before you start.** Billing → Budgets → create a monthly
cost budget with an alert at $10. It is the cheapest insurance available.

> For a portfolio, a screen recording plus the README architecture section
> carries most of the value. A live URL is a nice extra, not a requirement to
> keep running indefinitely.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Service stuck in *Operation in progress* then fails | Health check failing. Check *Application logs* in the console. |
| `llm_ready: false` | Secret not injected. Verify the instance role has `GetSecretValue` on that ARN. |
| `retriever_ready: false` | Index missing from the image. Should not happen; the pipeline verifies it. |
| Deployment fails pulling image | ECR access role missing or wrong region. |
| `environment: development` | The `ENVIRONMENT` variable was not set on the service. |
