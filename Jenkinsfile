// Push-based CD: lint -> test -> SonarQube gate -> build -> Trivy -> ECR -> Helm staging -> smoke test
//                -> manual approval -> Helm production.
pipeline {
  agent any

  environment {
    AWS_REGION   = 'us-east-1'
    CLUSTER_NAME = 'taskflow-eks'
    ECR_REPO     = 'taskflow-api'
    IMAGE_TAG    = "${env.BUILD_NUMBER}-${env.GIT_COMMIT.take(7)}"
    SCANNER_HOME = tool 'sonar-scanner'
  }

  options {
    timestamps()
    timeout(time: 60, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '20'))
    disableConcurrentBuilds()
  }

  triggers {
    githubPush()
  }

  stages {
    stage('Set up') {
      steps {
        script {
          env.AWS_ACCOUNT_ID = sh(script: 'aws sts get-caller-identity --query Account --output text', returnStdout: true).trim()
          env.REGISTRY = "${env.AWS_ACCOUNT_ID}.dkr.ecr.${env.AWS_REGION}.amazonaws.com"
          env.IMAGE = "${env.REGISTRY}/${env.ECR_REPO}:${env.IMAGE_TAG}"
        }
        sh '''
          python3 -m venv .venv
          . .venv/bin/activate
          pip install -q -r requirements-dev.txt
        '''
      }
    }

    stage('Lint') {
      steps {
        sh '. .venv/bin/activate && ruff check . && ruff format --check .'
      }
    }

    stage('Helm lint') {
      steps {
        sh 'helm lint helm/taskflow -f helm/taskflow/values-production.yaml'
        sh 'helm template taskflow helm/taskflow -f helm/taskflow/values-production.yaml > /dev/null'
      }
    }

    stage('Unit tests') {
      steps {
        sh '. .venv/bin/activate && pytest'
      }
      post {
        always { junit 'test-results.xml' }
      }
    }

    stage('SonarQube analysis') {
      steps {
        withSonarQubeEnv('sonarqube') {
          sh '''
            $SCANNER_HOME/bin/sonar-scanner \
              -Dsonar.projectKey=taskflow-api \
              -Dsonar.sources=app \
              -Dsonar.tests=tests \
              -Dsonar.python.version=3.12 \
              -Dsonar.python.coverage.reportPaths=coverage.xml \
              -Dsonar.python.xunit.reportPath=test-results.xml
          '''
        }
      }
    }

    stage('Quality gate') {
      steps {
        timeout(time: 5, unit: 'MINUTES') {
          waitForQualityGate abortPipeline: true
        }
      }
    }

    stage('Build image') {
      steps {
        sh 'docker build --build-arg APP_VERSION=$IMAGE_TAG -t $IMAGE .'
      }
    }

    stage('Trivy scan') {
      steps {
        sh 'trivy image --exit-code 1 --ignore-unfixed --severity CRITICAL,HIGH --no-progress $IMAGE'
      }
    }

    stage('Push to ECR') {
      when { branch 'main' }
      steps {
        sh '''
          aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $REGISTRY
          docker push $IMAGE
        '''
      }
    }

    stage('Deploy to staging') {
      when { branch 'main' }
      steps {
        sh '''
          aws eks update-kubeconfig --region $AWS_REGION --name $CLUSTER_NAME
          helm upgrade --install taskflow helm/taskflow \
            --namespace staging --create-namespace \
            -f helm/taskflow/values-staging.yaml \
            --set image.repository=$REGISTRY/$ECR_REPO \
            --set image.tag=$IMAGE_TAG \
            --atomic --wait --timeout 5m
        '''
      }
    }

    stage('Smoke test staging') {
      when { branch 'main' }
      steps {
        // Port-forward instead of a public endpoint: staging stays private.
        sh '''
          kubectl -n staging port-forward svc/taskflow 18000:80 >/dev/null 2>&1 &
          PF=$!
          trap "kill $PF" EXIT
          sleep 5
          curl -fsS http://127.0.0.1:18000/healthz
          curl -fsS http://127.0.0.1:18000/version | grep -q "$IMAGE_TAG"
          curl -fsS -X POST -H 'Content-Type: application/json' -d '{"title":"smoke"}' http://127.0.0.1:18000/tasks
        '''
      }
    }

    stage('Approve production') {
      when { branch 'main' }
      steps {
        timeout(time: 30, unit: 'MINUTES') {
          input message: "Deploy ${env.IMAGE_TAG} to production?", ok: 'Deploy'
        }
      }
    }

    stage('Deploy to production') {
      when { branch 'main' }
      steps {
        sh '''
          helm upgrade --install taskflow helm/taskflow \
            --namespace production --create-namespace \
            -f helm/taskflow/values-production.yaml \
            --set image.repository=$REGISTRY/$ECR_REPO \
            --set image.tag=$IMAGE_TAG \
            --atomic --wait --timeout 5m
          kubectl -n production rollout status deploy/taskflow
        '''
      }
    }
  }

  post {
    always {
      sh 'docker rmi $IMAGE || true'
      cleanWs()
    }
    failure {
      echo 'Build failed. With --atomic, Helm has already rolled back any failed release.'
    }
  }
}
