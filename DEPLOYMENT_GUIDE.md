# Railway Deployment Guide

## Overview
This guide will help you deploy your AutoCRM backend to Railway using the automated deployment scripts.

## Prerequisites
- Git repository with committed code
- Railway account (sign up at https://railway.app)
- Node.js/npm installed (for Railway CLI)

## One-Time Setup

### 1. Install Railway CLI

**Windows (PowerShell):**
```powershell
iwr https://railway.app/install.ps1 | iex
```

**macOS/Linux:**
```bash
npm install -g @railway/cli
# or
bash <(curl -fsSL cli.new/railway)
```

### 2. Login to Railway
```bash
railway login
```

### 3. Create/Link Railway Project
```bash
railway init  # Create new project
# or
railway link  # Link to existing project
```

## Deployment

### Automated Deployment (Recommended)

**Windows:**
```powershell
.\deploy.ps1
```

**macOS/Linux:**
```bash
chmod +x deploy.sh
./deploy.sh
```

The script will:
1. ✓ Check Railway CLI installation
2. ✓ Verify authentication (prompts `railway login` if needed)
3. ✓ Check project linking (offers `railway init` if none)
4. ✓ Warn about uncommitted changes and ask before continuing
5. ✓ Deploy with `railway up`
6. ✓ Offer to open the deployment

The scripts do not modify git state and do not run migrations.

### Manual Deployment

If you prefer manual control:

```bash
# 1. Ensure you're logged in
railway whoami

# 2. Check project status
railway status

# 3. Deploy
railway up

# 4. Open deployment
railway open
```

## Environment Variables

After first deployment, configure environment variables in Railway dashboard:

### Required Variables:
```
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-<region>.pooler.supabase.com:6543/postgres?sslmode=require
JWT_SECRET_KEY=<min-32-char-random-secret>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
DEBUG=False
FRONTEND_BASE_URL=https://<your-frontend-domain>
```

`DEBUG=False` is important in production: it makes auth cookies `Secure` and
causes `app/core/startup_checks.py` to abort startup on unsafe configuration.

### Recommended Variables:
```
# Invite + notification email
MAILJET_API_KEY=
MAILJET_SECRET_KEY=
MAILJET_SENDER_EMAIL=
MAILJET_SENDER_NAME=AutoCRM

# AI service callbacks
AI_SERVICE_BASE_URL=https://<your-ai-service-host>
AI_SERVICE_WEBHOOK_TOKEN=<shared-token>
AI_TRANSCRIPTION_NOTIFY_ENABLED=true

# Avatar storage (optional Supabase S3)
AVATAR_PUBLIC_BASE_URL=https://<your-backend-domain>
S3_ENDPOINT=
S3_ACCESS_KEY=
S3_SECRET_KEY=
```

Never commit real values. Set them only in the Railway dashboard or a secret
manager. AI service credentials are generated from **Profile Settings →
Developer Mode**; the backend stores only hashed tokens, so no raw AI service
token belongs in these variables.

### Setting Variables:

**Via Railway Dashboard:**
1. Go to your project on railway.app
2. Click on your service
3. Go to "Variables" tab
4. Add each variable with "New Variable" button

**Via CLI:**
```bash
railway variables set DATABASE_URL=<value>
railway variables set JWT_SECRET_KEY=<value>
railway variables set DEBUG=False
```

## Database Migration

Migrations are not run automatically by the start command. After deployment and
configuring environment variables, apply them explicitly:

```bash
railway run python -m alembic upgrade head
railway run python -m alembic current
```

Re-run this whenever a release adds new Alembic revisions. See
`MIGRATION_GUIDE.md` for details.

## Allow the Frontend Origin

CORS origins are hardcoded in `app/main.py`. A deployed frontend domain must be
added to `allow_origins` there and redeployed, because `allow_credentials=True`
means wildcard origins are rejected and cookie auth will fail silently in the
browser.

## Verify Deployment

### Check Deployment Status
```bash
railway status
```

### View Logs
```bash
railway logs
```

### Get Deployment URL
```bash
railway open
```

### Test API
```bash
curl https://your-railway-url.railway.app/health
curl https://your-railway-url.railway.app/docs
```

`GET /health` returns `{"status": "healthy"}` and `GET /` returns the service
banner.

## Deployment Files Overview

- **Procfile**: Defines the web process command
- **railway.json**: Railway deployment configuration
- **runtime.txt**: Specifies Python version (3.13.5)
- **requirements.txt**: Python dependencies
- **deploy.ps1**: Windows deployment script
- **deploy.sh**: Unix/Linux deployment script

## Troubleshooting

### Deployment Fails
```bash
# View detailed logs
railway logs

# Check project status
railway status

# Retry deployment
railway up --detach
```

### Database Connection Issues
- Verify DATABASE_URL is correctly set
- Check Supabase connection pooler is enabled
- Ensure password is URL-encoded if it contains special characters

### Import Errors
- Verify all requirements are in requirements.txt
- Check runtime.txt has correct Python version
- Review build logs: `railway logs --build`

### Port Issues
Railway automatically sets $PORT environment variable. Ensure Procfile uses:
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Useful Commands

```bash
# View environment variables
railway variables

# Open Railway dashboard
railway open

# Connect to shell in deployment
railway run bash

# View recent deployments
railway logs --deployment

# Rollback to previous deployment
# (via Railway dashboard only)

# Delete project
railway delete
```

## Continuous Deployment

Railway can auto-deploy on Git push:

1. Go to Railway dashboard
2. Select your service
3. Go to "Settings" tab
4. Under "Deployment", enable "Auto-Deploy"
5. Connect your GitHub repository

After setup, every push to your connected branch will trigger automatic deployment.

## Cost Considerations

Railway is a paid platform with usage-based billing on top of a monthly plan
credit. Check the current plans and pricing at https://railway.app/pricing and
monitor usage in the Railway dashboard to avoid unexpected charges.

## Next Steps

1. ✅ Deploy backend to Railway
2. ✅ Configure environment variables (`DEBUG=False`, `DATABASE_URL`, `JWT_SECRET_KEY`)
3. ✅ Run database migrations
4. ✅ Add the frontend origin to `allow_origins` in `app/main.py`
5. ✅ Test `/health` and `/docs`
6. ⏭️ Point the frontend at the Railway URL
7. ⏭️ Set up a custom domain (optional)
8. ⏭️ Enable auto-deployment from GitHub

## Support

- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Project Issues: Create issue in your repository
