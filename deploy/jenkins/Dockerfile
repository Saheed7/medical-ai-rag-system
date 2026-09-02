# =============================================================================
# Custom Jenkins controller image.
#
# Adds the tools the pipeline needs: Docker CLI, AWS CLI v2, Trivy, jq.
#
# DESIGN NOTE - Docker-outside-of-Docker (DooD)
# This image ships only the Docker *client*. At runtime the host's Docker
# socket is mounted in, so `docker build` executes on the host daemon.
#
# The alternative, Docker-in-Docker, runs a nested daemon and requires
# --privileged, which grants effectively unrestricted host access. DooD needs
# no privileged flag, reuses the host's layer cache (much faster rebuilds),
# and avoids nested-storage-driver problems.
#
# Both approaches still give pipeline code host-root-equivalent power via the
# socket. Neither is appropriate for untrusted multi-tenant builds; for those,
# use a rootless builder such as Kaniko or BuildKit. For a single-tenant local
# controller this is the right trade-off.
# =============================================================================
FROM jenkins/jenkins:lts-jdk17

USER root

# Retained so the cached layers below stay valid; see the Trivy step for
# how to pin a version through APT instead.
ARG TRIVY_VERSION=0.58.1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release unzip jq python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# --- Docker CLI only: no daemon, no containerd ---
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# --- AWS CLI v2 ---
RUN ARCH=$(uname -m) && \
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o /tmp/awscli.zip && \
    unzip -q /tmp/awscli.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/awscli.zip /tmp/aws

# --- Aqua Trivy, from the signed APT repository ---
# Deliberately NOT the `curl ... | sh` install script. In March 2026 an attacker
# with compromised credentials published a malicious Trivy release and rewrote
# the tags of aquasecurity/trivy-action to point at credential-stealing malware.
# Piping an unpinned script from a mutable branch into a root shell is exactly
# that attack surface. APT verifies the repository GPG signature before it
# installs anything, and it retries transfers - which also makes it far more
# reliable on a slow link than a single unretried tarball fetch.
#
# The signing key was rotated in April 2026 (Trivy v0.70.0); this fetches the
# current key. To pin a version, use: apt-get install -y trivy=<version>
RUN curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
        https://aquasecurity.github.io/trivy-repo/deb/public.key \
        | gpg --dearmor > /usr/share/keyrings/trivy.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/trivy.gpg] \
https://aquasecurity.github.io/trivy-repo/deb generic main" \
        > /etc/apt/sources.list.d/trivy.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends trivy && \
    rm -rf /var/lib/apt/lists/* && \
    trivy --version

# The jenkins user must be able to talk to the mounted host socket. The GID is
# overridden at build time to match the host's docker group:
#   docker build --build-arg DOCKER_GID=$(getent group docker | cut -d: -f3) ...
# On Docker Desktop for Windows the socket is proxied and group ownership is
# not enforced, so the default is fine there.
ARG DOCKER_GID=999
RUN if getent group docker >/dev/null; then \
        groupmod -g ${DOCKER_GID} docker 2>/dev/null || true; \
    else \
        groupadd -g ${DOCKER_GID} docker 2>/dev/null || true; \
    fi && \
    usermod -aG docker jenkins

USER jenkins

# Preinstall the plugins the pipeline needs, so first boot is not a manual
# click-through. Versions float deliberately: pinning Jenkins plugins tends to
# produce unresolvable dependency sets on upgrade.
# Plugin names must be separated by SINGLE spaces on one line. A multi-line
# continuation keeps the leading indentation after Docker joins the lines,
# and the CLI splits on a single space - so each run of spaces becomes an
# empty plugin name and the build fails requesting "/latest/.hpi".
#
# aws-credentials is included here: the Jenkinsfile's
# AmazonWebServicesCredentialsBinding comes from it, and without it the
# pipeline fails with an opaque class-not-found error.
RUN jenkins-plugin-cli --plugins "workflow-aggregator git github github-branch-source docker-workflow pipeline-stage-view credentials-binding aws-credentials timestamper ws-cleanup junit warnings-ng"
