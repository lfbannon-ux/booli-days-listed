#!/bin/bash
# Setup script for Booli Scraper
# Run this after cloning/creating the repo

set -e

echo "=========================================="
echo "Booli Scraper - Setup Script"
echo "=========================================="
echo ""

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    git branch -M main
fi

# Add all files
echo "Adding files to git..."
git add .

# Commit
echo "Creating initial commit..."
git commit -m "Initial commit: Booli scraper for Railway deployment" || echo "No changes to commit"

echo ""
echo "=========================================="
echo "NEXT STEPS:"
echo "=========================================="
echo ""
echo "1. CREATE GITHUB REPO:"
echo "   Go to https://github.com/new"
echo "   Name: booli-scraper"
echo "   Make it private (recommended)"
echo ""
echo "2. PUSH TO GITHUB:"
echo "   git remote add origin https://github.com/YOUR_USERNAME/booli-scraper.git"
echo "   git push -u origin main"
echo ""
echo "3. DEPLOY TO RAILWAY:"
echo "   a) Go to https://railway.app/new"
echo "   b) Select 'Deploy from GitHub repo'"
echo "   c) Choose 'booli-scraper'"
echo "   d) Railway will build using the Dockerfile"
echo ""
echo "4. SET ENVIRONMENT VARIABLES IN RAILWAY:"
echo "   Go to your project → Variables → Add these:"
echo ""
echo "   SMTP_HOST=smtp.gmail.com"
echo "   SMTP_PORT=587"
echo "   SMTP_USER=your-email@gmail.com"
echo "   SMTP_PASSWORD=your-app-password"
echo "   EMAIL_TO=recipient@example.com"
echo "   NUM_WORKERS=5"
echo ""
echo "   For Gmail, create an App Password at:"
echo "   https://myaccount.google.com/apppasswords"
echo ""
echo "5. SET UP SCHEDULED RUNS (Optional):"
echo "   In Railway → Settings → Cron, add:"
echo "   0 6 * * 0"
echo "   (Runs every Sunday at 6 AM UTC)"
echo ""
echo "6. TEST IT:"
echo "   Click 'Deploy' in Railway to run immediately"
echo ""
echo "=========================================="
