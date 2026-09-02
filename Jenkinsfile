// =============================================================================
// Medical AI RAG System - CI/CD pipeline
//
//   Checkout -> Quality gate -> Fetch index -> Build image
//            -> Trivy scan -> Push to ECR -> Deploy to App Runner
//
// No account identifiers appear here. Everything environment-specific comes
// from Jenkins credentials, so this file is safe to commit publicly.
// =============================================================================

pipeline {
    agent any

    options {
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '15'))
        timeout(time: 45, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    environment {
        // Captured by each stage so the post block can report the real
        // failure point. env.STAGE_NAME inside post{} evaluates to the post
        // block's own name, which is misleading.
        FAILED_STAGE = ''
        AWS_REGION     = "${params.AWS_REGION}"
        ECR_REPO       = "${params.ECR_REPO}"
        IMAGE_TAG      = "${env.GIT_COMMIT.take(7)}"
        ARTIFACT_BUCKET = "${params.ARTIFACT_BUCKET}"
        // Injected from a Jenkins "Secret text" credential; never echoed.
        AWS_ACCOUNT_ID = credentials('aws-account-id')
    }

    parameters {
        string(name: 'AWS_REGION', defaultValue: 'us-east-1',
               description: 'AWS region for ECR and App Runner')
        string(name: 'ECR_REPO', defaultValue: 'medical-ai-rag-system',
               description: 'ECR repository name')
        string(name: 'ARTIFACT_BUCKET', defaultValue: '',
               description: 'S3 bucket holding the FAISS index artifact')
        booleanParam(name: 'DEPLOY', defaultValue: false,
               description: 'Deploy to App Runner after a successful push')
        booleanParam(name: 'FAIL_ON_VULNS', defaultValue: true,
               description: 'Fail the build on HIGH/CRITICAL findings')
    }

    stages {

        stage('Checkout') {
            steps {
                script { env.FAILED_STAGE = 'Checkout' }
                checkout scm
                sh 'git --no-pager log -1 --oneline'
            }
        }

        stage('Quality gate') {
            // Mirrors the GitHub Actions job. Cheap, and fails before we spend
            // time building an image from code that does not lint or test.
            steps {
                script { env.FAILED_STAGE = 'Quality gate' }
                sh '''
                    set -eu
                    python3 -m venv .ci-venv
                    . .ci-venv/bin/activate
                    pip install --quiet --upgrade pip
                    pip install --quiet --upgrade setuptools wheel
                    pip install --quiet ruff pytest pytest-cov \
                        pydantic pydantic-settings 'langchain-core>=1.6.1' \
                        'langchain-text-splitters>=1.0.0' \
                        'langchain-community>=0.4.2' \
                        'langchain-huggingface>=1.2.2' 'pypdf>=6.16.2'
                    ruff check app tests scripts
                    pytest -q --junitxml=pytest-report.xml
                '''
            }
            post {
                always { junit allowEmptyResults: true, testResults: 'pytest-report.xml' }
            }
        }

        stage('Fetch index artifact') {
            // The FAISS index is derived from a copyrighted corpus and is not
            // in Git. The committed manifest pins an exact S3 object plus its
            // SHA-256, so every build uses byte-identical retrieval data.
            steps {
                script { env.FAILED_STAGE = 'Fetch index artifact' }
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                                  credentialsId: 'aws-credentials']]) {
                    sh '''
                        set -eu
                        . .ci-venv/bin/activate
                        python scripts/fetch_index.py --force --region "${AWS_REGION}"
                        test -f vectorstore/faiss_index/index.faiss
                    '''
                }
            }
        }

        stage('Build image') {
            steps {
                script { env.FAILED_STAGE = 'Build image' }
                sh '''
                    set -eu
                    # --provenance/--sbom disabled: BuildKit attaches an
                    # attestation that Trivy reads INSTEAD of the filesystem,
                    # and it can report package versions that are not actually
                    # in the image. Scanning the real layers is what we want.
                    docker build \
                        --provenance=false \
                        --sbom=false \
                        -t "${ECR_REPO}:${IMAGE_TAG}" \
                        -t "${ECR_REPO}:latest" \
                        .
                    docker image inspect "${ECR_REPO}:${IMAGE_TAG}" \
                        --format 'image size: {{.Size}} bytes'
                '''
            }
        }

        stage('Security scan') {
            steps {
                script { env.FAILED_STAGE = 'Security scan' }
                sh '''
                    set -eu
                    mkdir -p reports

                    # Human-readable summary in the console.
                    trivy image --severity HIGH,CRITICAL --no-progress \
                        --format table "${ECR_REPO}:${IMAGE_TAG}" \
                        | tee reports/trivy-summary.txt

                    # Machine-readable report retained as a build artifact.
                    trivy image --severity HIGH,CRITICAL --no-progress \
                        --format json -o reports/trivy-report.json \
                        "${ECR_REPO}:${IMAGE_TAG}"
                '''
                script {
                    if (params.FAIL_ON_VULNS) {
                        // --exit-code 1 turns findings into a build failure.
                        // Base images accrue CVEs over time, so this is a
                        // parameter rather than an unconditional gate.
                        sh '''
                            trivy image --severity HIGH,CRITICAL --no-progress \
                                --ignore-unfixed --exit-code 1 \
                                "${ECR_REPO}:${IMAGE_TAG}"
                        '''
                    }
                }
            }
            post {
                always { archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true }
            }
        }

        stage('Push to ECR') {
            steps {
                script { env.FAILED_STAGE = 'Push to ECR' }
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                                  credentialsId: 'aws-credentials']]) {
                    sh '''
                        set -eu
                        REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

                        # Create the repository on first run; harmless afterwards.
                        aws ecr describe-repositories \
                            --repository-names "${ECR_REPO}" \
                            --region "${AWS_REGION}" >/dev/null 2>&1 \
                        || aws ecr create-repository \
                            --repository-name "${ECR_REPO}" \
                            --image-scanning-configuration scanOnPush=true \
                            --region "${AWS_REGION}"

                        aws ecr get-login-password --region "${AWS_REGION}" \
                            | docker login --username AWS --password-stdin "${REGISTRY}"

                        docker tag "${ECR_REPO}:${IMAGE_TAG}" "${REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
                        docker tag "${ECR_REPO}:${IMAGE_TAG}" "${REGISTRY}/${ECR_REPO}:latest"

                        docker push "${REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
                        docker push "${REGISTRY}/${ECR_REPO}:latest"

                        echo "Pushed ${REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
                    '''
                }
            }
        }

        stage('Deploy to App Runner') {
            when { expression { params.DEPLOY } }
            steps {
                script { env.FAILED_STAGE = 'Deploy to App Runner' }
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                                  credentialsId: 'aws-credentials']]) {
                    sh '''
                        set -eu
                        SERVICE_ARN=$(aws apprunner list-services \
                            --region "${AWS_REGION}" \
                            --query "ServiceSummaryList[?ServiceName=='${ECR_REPO}'].ServiceArn" \
                            --output text)

                        if [ -z "${SERVICE_ARN}" ]; then
                            echo "No App Runner service named '${ECR_REPO}' found."
                            echo "Create it once in the console, then re-run with DEPLOY."
                            exit 1
                        fi

                        aws apprunner start-deployment \
                            --service-arn "${SERVICE_ARN}" \
                            --region "${AWS_REGION}"
                        echo "Deployment triggered for ${SERVICE_ARN}"
                    '''
                }
            }
        }
    }

    post {
        always {
            sh '''
                docker logout "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" 2>/dev/null || true
                docker image prune -f --filter "until=72h" 2>/dev/null || true
                rm -rf .ci-venv
            '''
            cleanWs(deleteDirs: true, notFailBuild: true)
        }
        success { echo "Pipeline succeeded: ${env.ECR_REPO}:${env.IMAGE_TAG}" }
        failure { echo "Pipeline failed at stage: ${env.FAILED_STAGE ?: 'unknown'}" }
    }
}
