# AutoCRM Railway Deployment Script
# Run: powershell -ExecutionPolicy Bypass -File deploy.ps1

Write-Host "AutoCRM Railway Deployment" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check if Railway CLI is installed
$railwayCli = Get-Command railway -ErrorAction SilentlyContinue
if (-not $railwayCli) {
    Write-Host "Railway CLI is not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Railway CLI:" -ForegroundColor Yellow
    Write-Host "  npm install -g @railway/cli" -ForegroundColor White
    exit 1
}

Write-Host "[OK] Railway CLI found" -ForegroundColor Green

# Check if logged in to Railway
Write-Host ""
Write-Host "Checking Railway authentication..." -ForegroundColor Yellow
railway whoami *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in to Railway" -ForegroundColor Red
    Write-Host ""
    Write-Host "Logging in to Railway..." -ForegroundColor Yellow
    railway login
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Login failed" -ForegroundColor Red
        exit 1
    }
}

Write-Host "[OK] Authenticated with Railway" -ForegroundColor Green

# Check if Railway project is linked
Write-Host ""
Write-Host "Checking Railway project..." -ForegroundColor Yellow
railway status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "No Railway project linked" -ForegroundColor Yellow
    Write-Host ""
    $createNew = Read-Host "Create new Railway project? (y/n)"

    if ($createNew -eq "y" -or $createNew -eq "Y") {
        Write-Host ""
        Write-Host "Creating new Railway project..." -ForegroundColor Yellow
        railway init
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Project creation failed" -ForegroundColor Red
            exit 1
        }
        Write-Host "[OK] Project created" -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "Link existing project with: railway link" -ForegroundColor Yellow
        exit 0
    }
}

Write-Host "[OK] Railway project linked" -ForegroundColor Green

# Check for uncommitted changes
Write-Host ""
Write-Host "Checking Git status..." -ForegroundColor Yellow
$gitStatus = git status --porcelain
if ($gitStatus) {
    Write-Host "You have uncommitted changes" -ForegroundColor Yellow
    Write-Host ""
    $commit = Read-Host "Commit and push changes? (y/n)"

    if ($commit -eq "y" -or $commit -eq "Y") {
        Write-Host ""
        $message = Read-Host "Commit message (or press Enter for default)"
        if ([string]::IsNullOrWhiteSpace($message)) {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
            $message = "Deploy to Railway - $timestamp"
        }

        Write-Host "Committing changes..." -ForegroundColor Yellow
        git add .
        git commit -m $message

        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Changes committed" -ForegroundColor Green

            Write-Host ""
            Write-Host "Pushing to remote..." -ForegroundColor Yellow
            git push

            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Changes pushed" -ForegroundColor Green
            }
            else {
                Write-Host "Push failed, but continuing with deployment" -ForegroundColor Yellow
            }
        }
    }
}

# Deploy to Railway
Write-Host ""
Write-Host "Deploying to Railway..." -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

railway up

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Deployment successful!" -ForegroundColor Green
    Write-Host ""
    Write-Host "View your deployment: railway open" -ForegroundColor Yellow
    Write-Host "View logs: railway logs" -ForegroundColor Yellow
    Write-Host ""

    $openDeploy = Read-Host "Open deployment in browser? (y/n)"
    if ($openDeploy -eq "y" -or $openDeploy -eq "Y") {
        railway open
    }
}
else {
    Write-Host ""
    Write-Host "Deployment failed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check logs with: railway logs" -ForegroundColor Yellow
    exit 1
}
