# Jenkins setup

Everything here uses **your own** AWS, GitHub and Docker accounts. No
credential is written into a file — all secrets live in Jenkins' credential
store and are injected at run time.

---

## 1. AWS prerequisites (one-off)

### Create an IAM user for CI

Console → IAM → Users → **Create user** → name `jenkins-ci`.
Do **not** give it console access. Attach these managed policies:

| Policy | Why |
|---|---|
| `AmazonEC2ContainerRegistryFullAccess` | create repo, push images |
| `AWSAppRunnerFullAccess` | trigger deployments |
| `AmazonS3ReadOnlyAccess` | fetch the index artifact |

> Managed policies keep this short. For real work, scope a custom policy to the
> single ECR repository, the single App Runner service, and the one S3 prefix.

Create an **access key** for the user (Security credentials → Create access
key → *Application running outside AWS*). Copy both values now; the secret is
shown once.

### Create the artifact bucket

```bash
aws s3 mb s3://YOUR-UNIQUE-BUCKET-NAME --region us-east-1
aws s3api put-public-access-block \
  --bucket YOUR-UNIQUE-BUCKET-NAME \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

The bucket must stay private: the index contains verbatim text from a
copyrighted corpus.

### Publish your index

From the project root, with your local index already built:

```bash
python scripts/publish_index.py --bucket YOUR-UNIQUE-BUCKET-NAME --version v1
git add vectorstore/INDEX_MANIFEST.json
git commit -m "Publish FAISS index v1"
git push
```

The manifest records the S3 URI, SHA-256, vector count, and the chunking and
embedding parameters that produced the index. CI fetches by that manifest, so
every build uses byte-identical retrieval data — and a checksum mismatch fails
the build rather than silently shipping a different index.

---

## 2. Build and start Jenkins

```bash
cd deploy/jenkins

# Linux/macOS: match the host docker group
export DOCKER_GID=$(getent group docker | cut -d: -f3)
# Windows/Docker Desktop: skip the line above, the default works

docker compose up -d --build
docker compose logs -f jenkins
```

First build takes several minutes (Docker CLI, AWS CLI, Trivy, plugins), and
much longer on a slow connection - the Jenkins base image alone is ~250 MB.
Layers are cached, so a failed build resumes rather than restarting.

If `docker compose` reports "failed to read dockerfile" while the file is
plainly there, it found a compose file in a parent directory and resolved
paths relative to that. Build explicitly instead:

```bash
cd deploy/jenkins
docker build -t medical-rag-jenkins:latest .
docker compose -f docker-compose.yml up -d
```

Open <http://localhost:8090>. The initial admin password:

```bash
docker exec medical-rag-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Choose **Install suggested plugins**, then create your admin user.

### Confirm the tooling

```bash
docker exec medical-rag-jenkins docker --version
docker exec medical-rag-jenkins aws --version
docker exec medical-rag-jenkins trivy --version
```

If `docker --version` works but pipeline builds report a permission error on
`/var/run/docker.sock`, the group ID did not match. Rebuild with the correct
`DOCKER_GID`.

---

## 3. Credentials

**Manage Jenkins → Credentials → System → Global credentials → Add.**

| Kind | ID | Contents |
|---|---|---|
| AWS Credentials | `aws-credentials` | Access key + secret for `jenkins-ci` |
| Secret text | `aws-account-id` | Your 12-digit AWS account ID |
| Username with password | `github-credentials` | GitHub username + a PAT (`repo` scope) |

The AWS Credentials kind needs the **CloudBees AWS Credentials** plugin:
Manage Jenkins → Plugins → Available → search `AWS Credentials` → install.

Find your account ID with:

```bash
aws sts get-caller-identity --query Account --output text
```

It is treated as a secret here only to keep it out of public build logs — it
is an identifier, not a credential.

---

## 4. Create the pipeline job

**New Item** → name `medical-ai-rag-system` → **Pipeline** → OK.

- **Build Triggers** → tick *GitHub hook trigger for GITScm polling*
- **Pipeline** → Definition: *Pipeline script from SCM*
  - SCM: **Git**
  - Repository URL: `https://github.com/YOUR-USERNAME/medical-ai-rag-system.git`
  - Credentials: `github-credentials`
  - Branch: `*/main`
  - Script Path: `Jenkinsfile`

Save, then **Build with Parameters** and set `ARTIFACT_BUCKET` to your bucket
name. Leave `DEPLOY` unticked for the first run.

---

## 5. GitHub webhook

Local Jenkins is not reachable from GitHub, so expose it with a tunnel:

```bash
ngrok http 8090
```

In your repo: **Settings → Webhooks → Add webhook**

- Payload URL: `https://YOUR-NGROK-ID.ngrok-free.app/github-webhook/`  (trailing slash matters)
- Content type: `application/json`
- Event: *Just the push event*

GitHub shows a green tick on the delivery when Jenkins accepts it.

> The ngrok URL changes each restart on the free tier. For a stable setup, run
> Jenkins on a small EC2 instance with a fixed address.

---

## 6. First run

Expect this sequence:

| Stage | What it does |
|---|---|
| Checkout | Clones the commit |
| Quality gate | `ruff` + `pytest`, publishes JUnit results |
| Fetch index artifact | Downloads from S3, verifies SHA-256 |
| Build image | `docker build` on the host daemon |
| Security scan | Trivy HIGH/CRITICAL, archives JSON report |
| Push to ECR | Creates repo if absent, pushes `:<sha>` and `:latest` |
| Deploy | Skipped unless `DEPLOY` is ticked |

### If the security scan fails the build

That is the gate working. Inspect `reports/trivy-summary.txt` in the build
artifacts. Options, in order of preference:

1. Rebuild — the base image may already have a patched version
2. Bump the affected pinned dependency in `requirements.txt`
3. Move to a newer `python:3.11-slim` digest
4. Only if the finding genuinely does not apply, re-run with
   `FAIL_ON_VULNS` unticked and record why

The scan uses `--ignore-unfixed`, so findings with no available patch do not
block. Failing on unfixable CVEs trains people to disable the gate.

---

## Why Docker-outside-of-Docker

Jenkins runs in a container but must build containers. Two standard options:

| | Docker-in-Docker | Docker-outside-of-Docker |
|---|---|---|
| Mechanism | Nested daemon inside Jenkins | Mount host `/var/run/docker.sock` |
| `--privileged` | Required | Not required |
| Layer cache | Isolated, cold every time | Shares the host cache |
| Storage driver | Nested-overlay problems | None |

This setup uses DooD. Both give pipeline code host-root-equivalent access
through the socket, so neither suits untrusted multi-tenant builds — those want
a rootless builder such as Kaniko or BuildKit. For a single-tenant controller,
DooD gives the same capability without `--privileged` and builds considerably
faster.
