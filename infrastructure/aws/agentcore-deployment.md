# AWS AgentCore Deployment Guide

This guide covers deploying Ops Agent to AWS using Amazon Bedrock and related services.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  EventBridge Scheduler                                          │
│  cron(0 */4 * * ? *)  →  POST /api/sweeps/follow-ups          │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  ECS Fargate Service                                            │
│  FastAPI backend (ops-agent:latest)                             │
│  Environment: OPS_MODEL_PROVIDER=bedrock                        │
│              OPS_AWS_REGION=us-west-2                           │
│              OPS_BEDROCK_MODEL_ID=global.anthropic.claude-...   │
└────────────────────────┬────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│  Bedrock     │  │  RDS        │  │  S3          │
│  (Claude)    │  │  Postgres   │  │  (sessions)  │
└──────────────┘  └─────────────┘  └──────────────┘
```

## Prerequisites

1. AWS account with:
   - Bedrock access in `us-west-2` or `us-east-1`
   - ECS cluster or ability to create one
   - RDS Postgres instance or RDS Serverless
   - S3 bucket for paused agent sessions

2. AWS CLI configured with appropriate credentials

3. Docker installed locally for building images

## Step 1: Create S3 bucket for agent sessions

```bash
export AWS_REGION=us-west-2
export BUCKET_NAME=ops-agent-sessions-$(aws sts get-caller-identity --query Account --output text)

aws s3 mb s3://${BUCKET_NAME} --region ${AWS_REGION}

# Block public access
aws s3api put-public-access-block \
  --bucket ${BUCKET_NAME} \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Enable versioning (recommended for session recovery)
aws s3api put-bucket-versioning \
  --bucket ${BUCKET_NAME} \
  --versioning-configuration Status=Enabled

# Lifecycle policy to clean up old sessions after 7 days
cat > /tmp/lifecycle.json <<EOF
{
  "Rules": [{
    "Id": "DeleteOldSessions",
    "Status": "Enabled",
    "Filter": { "Prefix": "ops-agent/sessions/" },
    "Expiration": { "Days": 7 }
  }]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
  --bucket ${BUCKET_NAME} \
  --lifecycle-configuration file:///tmp/lifecycle.json
```

## Step 2: Create RDS Postgres database

### Option A: RDS Postgres (recommended for production)

```bash
export DB_INSTANCE_ID=ops-agent-db
export DB_PASSWORD=$(openssl rand -base64 32)

aws rds create-db-instance \
  --db-instance-identifier ${DB_INSTANCE_ID} \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 16.1 \
  --master-username opsagent \
  --master-user-password ${DB_PASSWORD} \
  --allocated-storage 20 \
  --storage-type gp3 \
  --backup-retention-period 7 \
  --no-publicly-accessible \
  --vpc-security-group-ids sg-xxx \
  --db-subnet-group-name xxx \
  --region ${AWS_REGION}

# Wait for instance to be available
aws rds wait db-instance-available --db-instance-identifier ${DB_INSTANCE_ID}

# Get endpoint
export DB_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier ${DB_INSTANCE_ID} \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

export DATABASE_URL="postgresql+psycopg://opsagent:${DB_PASSWORD}@${DB_ENDPOINT}:5432/postgres"

echo "DATABASE_URL=${DATABASE_URL}" >> .env.production
echo "Store this securely: ${DB_PASSWORD}"
```

### Option B: RDS Serverless v2 (cost-optimized)

```bash
export CLUSTER_ID=ops-agent-cluster
export DB_PASSWORD=$(openssl rand -base64 32)

aws rds create-db-cluster \
  --db-cluster-identifier ${CLUSTER_ID} \
  --engine aurora-postgresql \
  --engine-version 16.1 \
  --master-username opsagent \
  --master-user-password ${DB_PASSWORD} \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=1 \
  --vpc-security-group-ids sg-xxx \
  --db-subnet-group-name xxx \
  --region ${AWS_REGION}

aws rds create-db-instance \
  --db-instance-identifier ${CLUSTER_ID}-instance-1 \
  --db-cluster-identifier ${CLUSTER_ID} \
  --db-instance-class db.serverless \
  --engine aurora-postgresql \
  --region ${AWS_REGION}
```

## Step 3: Create IAM role for ECS task

```bash
export ROLE_NAME=OpsAgentECSTaskRole

# Create trust policy
cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name ${ROLE_NAME} \
  --assume-role-policy-document file:///tmp/trust-policy.json

# Attach Bedrock policy
aws iam put-role-policy \
  --role-name ${ROLE_NAME} \
  --policy-name BedrockInvoke \
  --policy-document file://infrastructure/aws/bedrock-invoke-policy.json

# Attach S3 session storage policy
cat > /tmp/s3-session-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ],
    "Resource": [
      "arn:aws:s3:::${BUCKET_NAME}/ops-agent/sessions/*",
      "arn:aws:s3:::${BUCKET_NAME}"
    ]
  }]
}
EOF

aws iam put-role-policy \
  --role-name ${ROLE_NAME} \
  --policy-name S3SessionStorage \
  --policy-document file:///tmp/s3-session-policy.json
```

## Step 4: Build and push Docker image to ECR

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REPO=ops-agent
export IMAGE_TAG=latest

# Create ECR repository
aws ecr create-repository \
  --repository-name ${ECR_REPO} \
  --region ${AWS_REGION} || true

# Authenticate Docker to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Build image
cd backend
docker build -t ${ECR_REPO}:${IMAGE_TAG} .

# Tag and push
docker tag ${ECR_REPO}:${IMAGE_TAG} \
  ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}

docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}
```

## Step 5: Create ECS task definition

```bash
cat > /tmp/task-definition.json <<EOF
{
  "family": "ops-agent",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "taskRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ROLE_NAME}",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
  "containerDefinitions": [{
    "name": "ops-agent",
    "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}",
    "portMappings": [{
      "containerPort": 8010,
      "protocol": "tcp"
    }],
    "environment": [
      {"name": "OPS_MODEL_PROVIDER", "value": "bedrock"},
      {"name": "OPS_AWS_REGION", "value": "${AWS_REGION}"},
      {"name": "OPS_BEDROCK_MODEL_ID", "value": "global.anthropic.claude-sonnet-4-6"},
      {"name": "OPS_AGENT_SESSION_S3_BUCKET", "value": "${BUCKET_NAME}"},
      {"name": "OPS_DATABASE_URL", "value": "${DATABASE_URL}"},
      {"name": "OPS_API_HOST", "value": "0.0.0.0"},
      {"name": "OPS_API_PORT", "value": "8010"}
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/ops-agent",
        "awslogs-region": "${AWS_REGION}",
        "awslogs-stream-prefix": "ecs"
      }
    },
    "healthCheck": {
      "command": ["CMD-SHELL", "curl -f http://localhost:8010/health || exit 1"],
      "interval": 30,
      "timeout": 5,
      "retries": 3,
      "startPeriod": 60
    }
  }]
}
EOF

# Create CloudWatch log group
aws logs create-log-group --log-group-name /ecs/ops-agent --region ${AWS_REGION} || true

# Register task definition
aws ecs register-task-definition \
  --cli-input-json file:///tmp/task-definition.json \
  --region ${AWS_REGION}
```

## Step 6: Create ECS service

```bash
export CLUSTER_NAME=ops-agent-cluster
export SERVICE_NAME=ops-agent-service
export SUBNET_IDS="subnet-xxx,subnet-yyy"  # Replace with your subnet IDs
export SECURITY_GROUP_ID="sg-xxx"          # Replace with your security group

# Create cluster if it doesn't exist
aws ecs create-cluster --cluster-name ${CLUSTER_NAME} --region ${AWS_REGION} || true

# Create service
aws ecs create-service \
  --cluster ${CLUSTER_NAME} \
  --service-name ${SERVICE_NAME} \
  --task-definition ops-agent \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=ENABLED}" \
  --region ${AWS_REGION}
```

## Step 7: Initialize database

```bash
# Get task ARN
export TASK_ARN=$(aws ecs list-tasks \
  --cluster ${CLUSTER_NAME} \
  --service-name ${SERVICE_NAME} \
  --query 'taskArns[0]' \
  --output text \
  --region ${AWS_REGION})

# Run migrations via ECS Exec
aws ecs execute-command \
  --cluster ${CLUSTER_NAME} \
  --task ${TASK_ARN} \
  --container ops-agent \
  --interactive \
  --command "/app/.venv/bin/python -m scripts.init_db" \
  --region ${AWS_REGION}

# Seed with demo data (optional)
aws ecs execute-command \
  --cluster ${CLUSTER_NAME} \
  --task ${TASK_ARN} \
  --container ops-agent \
  --interactive \
  --command "/app/.venv/bin/python -m scripts.seed" \
  --region ${AWS_REGION}
```

## Step 8: Set up EventBridge scheduler for follow-ups

```bash
export SCHEDULE_NAME=ops-agent-followups
export TASK_DEFINITION_ARN=$(aws ecs describe-task-definition \
  --task-definition ops-agent \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text \
  --region ${AWS_REGION})

# Create IAM role for EventBridge scheduler
cat > /tmp/scheduler-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "scheduler.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name OpsAgentSchedulerRole \
  --assume-role-policy-document file:///tmp/scheduler-trust-policy.json

aws iam attach-role-policy \
  --role-name OpsAgentSchedulerRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonECSTaskExecutionRolePolicy

# Create schedule (every 4 hours)
aws scheduler create-schedule \
  --name ${SCHEDULE_NAME} \
  --schedule-expression "rate(4 hours)" \
  --flexible-time-window Mode=OFF \
  --target "{
    \"Arn\": \"arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:cluster/${CLUSTER_NAME}\",
    \"RoleArn\": \"arn:aws:iam::${AWS_ACCOUNT_ID}:role/OpsAgentSchedulerRole\",
    \"EcsParameters\": {
      \"TaskDefinitionArn\": \"${TASK_DEFINITION_ARN}\",
      \"LaunchType\": \"FARGATE\",
      \"NetworkConfiguration\": {
        \"awsvpcConfiguration\": {
          \"Subnets\": [${SUBNET_IDS}],
          \"SecurityGroups\": [\"${SECURITY_GROUP_ID}\"],
          \"AssignPublicIp\": \"ENABLED\"
        }
      },
      \"TaskCount\": 1
    },
    \"Input\": \"{\\\"path\\\":\\\"/api/sweeps/follow-ups\\\",\\\"method\\\":\\\"POST\\\"}\"
  }" \
  --region ${AWS_REGION}
```

## Step 9: Verify deployment

```bash
# Check service status
aws ecs describe-services \
  --cluster ${CLUSTER_NAME} \
  --services ${SERVICE_NAME} \
  --region ${AWS_REGION}

# View logs
aws logs tail /ecs/ops-agent --follow --region ${AWS_REGION}

# Test the API (if publicly accessible)
export TASK_PUBLIC_IP=$(aws ecs describe-tasks \
  --cluster ${CLUSTER_NAME} \
  --tasks ${TASK_ARN} \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text \
  --region ${AWS_REGION} | \
  xargs -I {} aws ec2 describe-network-interfaces \
    --network-interface-ids {} \
    --query 'NetworkInterfaces[0].Association.PublicIp' \
    --output text \
    --region ${AWS_REGION})

curl http://${TASK_PUBLIC_IP}:8010/health
curl http://${TASK_PUBLIC_IP}:8010/api/dashboard
```

## Cost Estimates (us-west-2, as of Sept 2026)

| Service | Configuration | Monthly Cost |
|---------|--------------|--------------|
| ECS Fargate | 0.5 vCPU, 1GB RAM, 24/7 | ~$15 |
| RDS t4g.micro | Postgres 16, 20GB storage | ~$15 |
| RDS Serverless v2 | 0.5-1 ACU, intermittent | ~$10-20 |
| S3 | Session storage, <1GB | <$1 |
| Bedrock | Claude Sonnet, ~100 runs/day | ~$20-40 |
| **Total** | | **~$60-90/month** |

Notes:
- Bedrock costs depend on token usage; 100 runs/day at 20-50s each ≈ 5M tokens/month
- RDS Serverless scales to zero when idle
- Consider using Fargate Spot for 70% cost reduction

## Troubleshooting

### Model access denied

```bash
# Run preflight from the container
aws ecs execute-command \
  --cluster ${CLUSTER_NAME} \
  --task ${TASK_ARN} \
  --container ops-agent \
  --interactive \
  --command "/app/.venv/bin/python -m scripts.preflight_bedrock --list" \
  --region ${AWS_REGION}
```

### Database connection issues

Check security group allows ECS task → RDS on port 5432.

### Session persistence failures

Verify the S3 bucket policy and IAM role permissions for `s3:PutObject` and `s3:GetObject`.

## Production Considerations

1. **Use Application Load Balancer** for HTTPS and multiple tasks
2. **Enable ECS Exec** for debugging: `--enable-execute-command` on service creation
3. **Set up CloudWatch alarms** for task failures and high CPU/memory
4. **Use Secrets Manager** for database credentials instead of environment variables
5. **Enable RDS automated backups** and set retention period
6. **Configure VPC endpoints** for Bedrock and S3 to avoid NAT gateway costs
7. **Use ECS autoscaling** based on CPU/memory or custom metrics
8. **Set up X-Ray tracing** for distributed tracing across services

## Alternative: AWS Lambda deployment

For lower-volume workloads (<100 runs/day), consider Lambda:
- Serverless, pay-per-invocation
- Cold starts acceptable for async operations
- RDS Proxy required for connection pooling
- Session storage must use S3 (ephemeral /tmp)

See [lambda-deployment.md](lambda-deployment.md) for details (coming soon).
