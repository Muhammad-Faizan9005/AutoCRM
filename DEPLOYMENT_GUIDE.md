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
2. ✓ Verify authentication
3. ✓ Check project linking
4. ✓ Check for uncommitted changes
5. ✓ Deploy to Railway
6. ✓ Provide post-deployment options

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
SUPABASE_URL=https://snwheczzakjyhfaitmoq.supabase.co
SUPABASE_KEY=your_supabase_key_here
DATABASE_URL=postgresql://postgres.xxxxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
jwt_secret_key=your_generated_secret_key
jwt_algorithm=HS256
jwt_access_token_expire_minutes=30
jwt_refresh_token_expire_days=7
```

### Setting Variables:

**Via Railway Dashboard:**
1. Go to your project on railway.app
2. Click on your service
3. Go to "Variables" tab
4. Add each variable with "New Variable" button

**Via CLI:**
```bash
railway variables set SUPABASE_URL=your_value_here
railway variables set SUPABASE_KEY=your_value_here
railway variables set DATABASE_URL=your_value_here
railway variables set jwt_secret_key=your_value_here
```

## Database Migration

After deployment and configuring environment variables, run migrations:

```bash
railway run alembic upgrade head
```

This will apply all pending database migrations to your Supabase database.

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
curl https://your-railway-url.railway.app/docs
```

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

Railway offers:
- **Hobby Plan**: $5/month credit (free trial available)
- **Pro Plan**: $20/month credit

Monitor usage in Railway dashboard to avoid unexpected charges.

## Next Steps

1. ✅ Deploy backend to Railway
2. ✅ Configure environment variables
3. ✅ Run database migrations
4. ✅ Test API endpoints
5. ⏭️ Update frontend to use Railway URL
6. ⏭️ Set up custom domain (optional)
7. ⏭️ Enable auto-deployment from GitHub

## Support

- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Project Issues: Create issue in your repository
