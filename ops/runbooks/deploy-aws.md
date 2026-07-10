# Deploying to AWS EC2

AWS-specific version of `ops/runbooks/deploy.md` -- an EC2 instance
running the exact same `docker-compose.prod.yml` + Caddy stack already
verified locally, with backups/uploads on real S3 instead of self-hosted
MinIO. No domain yet, so this uses the instance's bare IP: Caddy's
automatic HTTPS only issues real Let's Encrypt certificates for domain
names, so against a bare IP it falls back to its own internal
(self-signed) CA -- the app works identically, but browsers will show a
security warning until a real domain is pointed at it later (at which
point this is a one-line `.env` change, not a re-deploy).

Every command below uses the AWS CLI (`aws sso login` first, or
whichever auth method you use). Console steps are equivalent if you
prefer clicking through the UI instead.

## 1. Launch the EC2 instance

```bash
# Ubuntu 24.04 LTS AMI ID varies by region -- look it up for yours:
aws ec2 describe-images --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
             "Name=state,Values=available" \
  --query "sort_by(Images, &CreationDate)[-1].ImageId" --output text

# A key pair to SSH in with (skip if you already have one):
aws ec2 create-key-pair --key-name soulindia-prod \
  --query "KeyMaterial" --output text > soulindia-prod.pem
chmod 400 soulindia-prod.pem

# Security group: SSH restricted to your current IP, HTTP/HTTPS open to
# everyone (that's the point -- it's a public web app).
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 create-security-group --group-name soulindia-prod \
  --description "soulIndia production"
aws ec2 authorize-security-group-ingress --group-name soulindia-prod \
  --protocol tcp --port 22 --cidr "${MY_IP}/32"
aws ec2 authorize-security-group-ingress --group-name soulindia-prod \
  --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-name soulindia-prod \
  --protocol tcp --port 443 --cidr 0.0.0.0/0

# t3.medium (2 vCPU / 4 GB) matches the sizing this was load-tested
# against (docs/load-test.md); a 40 GB gp3 root volume gives headroom
# for Postgres + nightly backups beyond the current ~1 GB dataset.
aws ec2 run-instances \
  --image-id <AMI_ID_FROM_ABOVE> \
  --instance-type t3.medium \
  --key-name soulindia-prod \
  --security-groups soulindia-prod \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":40,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=soulindia-prod}]'

# A static IP that survives stop/start -- worth having even without a
# domain yet, so you don't have to reconfigure anything if the instance
# ever restarts.
aws ec2 allocate-address --domain vpc
aws ec2 associate-address --instance-id <INSTANCE_ID> --allocation-id <ALLOCATION_ID>
```

## 2. Create the S3 bucket + IAM instance role

Bucket names are globally unique across all of AWS -- pick something
specific, not the dev default (`retail-analytics-uploads` is almost
certainly already taken by someone else's account).

```bash
BUCKET=soulindia-prod-<something-unique-to-you>
REGION=ap-south-1   # or whichever region you launched the instance in

aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

Prefer an IAM instance role over static access keys -- no long-lived
credentials sitting on the box at all, and it's what `storage.py` is
already built to use automatically (boto3 falls back to the instance's
attached role when `OBJECT_STORAGE_ACCESS_KEY` isn't set in `.env`):

```bash
cat > trust-policy.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
aws iam create-role --role-name soulindia-prod-role \
  --assume-role-policy-document file://trust-policy.json

cat > bucket-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],
  "Resource":"arn:aws:s3:::${BUCKET}/*"},
  {"Effect":"Allow","Action":"s3:ListBucket",
  "Resource":"arn:aws:s3:::${BUCKET}"}]}
EOF
aws iam put-role-policy --role-name soulindia-prod-role \
  --policy-name s3-access --policy-document file://bucket-policy.json

aws iam create-instance-profile --instance-profile-name soulindia-prod-profile
aws iam add-role-to-instance-profile \
  --instance-profile-name soulindia-prod-profile --role-name soulindia-prod-role
aws ec2 associate-iam-instance-profile --instance-id <INSTANCE_ID> \
  --iam-instance-profile Name=soulindia-prod-profile
```

## 3. Install Docker on the instance

```bash
ssh -i soulindia-prod.pem ubuntu@<ELASTIC_IP>
```

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
sudo apt-get install -y docker-compose-plugin
```

## 4. Deploy

```bash
git clone <repo-url> soulIndia && cd soulIndia
cp .env.prod.example .env
```

Edit `.env`:
- `DJANGO_SECRET_KEY`: generate with `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`
- `POSTGRES_PASSWORD`: a real generated password
- `DOMAIN`: the Elastic IP itself (no domain yet -- see the note at the
  top of this file about the browser warning that implies)
- `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS`: the Elastic IP
- Object storage: use the **Option B (real AWS S3)** block already in
  `.env.prod.example` -- set `OBJECT_STORAGE_BUCKET` to the bucket name
  from step 2 and `OBJECT_STORAGE_REGION` to its region; leave
  `OBJECT_STORAGE_ACCESS_KEY`/`SECRET_KEY` **unset** so boto3 picks up
  the instance role automatically.

```bash
# Real S3 means the self-hosted MinIO service isn't needed -- skip
# starting it rather than editing any compose file:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build \
  --scale minio=0 --scale minio-init=0
```

Then follow `ops/runbooks/deploy.md` from step 5 onward (seed the
initial Super Admin, set up the nightly backup cron job, confirm
`https://<ELASTIC_IP>/health/` -- accept the browser's self-signed
certificate warning once, matching what's expected per the note at the
top of this file).

## Adding a real domain later

Point an A record at the Elastic IP, then on the instance:

```bash
sed -i "s/^DOMAIN=.*/DOMAIN=your-domain.example.com/" .env
sed -i "s/^DJANGO_ALLOWED_HOSTS=.*/DJANGO_ALLOWED_HOSTS=your-domain.example.com/" .env
sed -i "s#^DJANGO_CSRF_TRUSTED_ORIGINS=.*#DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.example.com#" .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Caddy notices the new `DOMAIN` and automatically obtains a real Let's
Encrypt certificate -- no other changes needed.
