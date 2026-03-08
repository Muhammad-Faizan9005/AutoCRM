#!/bin/bash
# AutoCRM Railway Deployment Script
# Run this script to deploy your backend to Railway

echo "🚀 AutoCRM Railway Deployment"
echo "================================"
echo ""

# Check if Railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI is not installed"
    echo ""
    echo "Install Railway CLI:"
    echo "npm install -g @railway/cli"
    echo ""
    echo "Or use curl:"
    echo "bash <(curl -fsSL cli.new/railway)"
    exit 1
fi

echo "✓ Railway CLI found"

# Check if logged in to Railway
echo ""
echo "Checking Railway authentication..."
if ! railway whoami &> /dev/null; then
    echo "❌ Not logged in to Railway"
    echo ""
    echo "Logging in to Railway..."
    railway login
    if [ $? -ne 0 ]; then
        echo "❌ Login failed"
        exit 1
    fi
fi

echo "✓ Authenticated with Railway"

# Check if Railway project is linked
echo ""
echo "Checking Railway project..."
if ! railway status &> /dev/null; then
    echo "⚠️  No Railway project linked"
    echo ""
    read -p "Create new Railway project? (y/n): " createNew
    
    if [[ $createNew == "y" || $createNew == "Y" ]]; then
        echo ""
        echo "Creating new Railway project..."
        railway init
        if [ $? -ne 0 ]; then
            echo "❌ Project creation failed"
            exit 1
        fi
        echo "✓ Project created"
    else
        echo ""
        echo "Link existing project with: railway link"
        exit 0
    fi
fi

echo "✓ Railway project linked"

# Check for uncommitted changes
echo ""
echo "Checking Git status..."
if [[ -n $(git status --porcelain) ]]; then
    echo "⚠️  You have uncommitted changes"
    echo ""
    read -p "Commit and push changes? (y/n): " commit
    
    if [[ $commit == "y" || $commit == "Y" ]]; then
        echo ""
        read -p "Commit message (or press Enter for default): " message
        if [[ -z "$message" ]]; then
            message="Deploy to Railway - $(date '+%Y-%m-%d %H:%M')"
        fi
        
        echo "Committing changes..."
        git add .
        git commit -m "$message"
        
        if [ $? -eq 0 ]; then
            echo "✓ Changes committed"
            
            echo ""
            echo "Pushing to remote..."
            git push
            
            if [ $? -eq 0 ]; then
                echo "✓ Changes pushed"
            else
                echo "⚠️  Push failed, but continuing with deployment"
            fi
        fi
    fi
fi

# Deploy to Railway
echo ""
echo "🚀 Deploying to Railway..."
echo "================================"
echo ""

railway up

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment successful!"
    echo ""
    echo "View your deployment:"
    echo "railway open"
    echo ""
    echo "View logs:"
    echo "railway logs"
    echo ""
    
    # Ask if user wants to open the deployment
    read -p "Open deployment in browser? (y/n): " openDeploy
    if [[ $openDeploy == "y" || $openDeploy == "Y" ]]; then
        railway open
    fi
else
    echo ""
    echo "❌ Deployment failed"
    echo ""
    echo "Check logs with: railway logs"
    exit 1
fi
