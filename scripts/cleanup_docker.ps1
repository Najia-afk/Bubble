# =============================================================================
# Bubble - Docker Cleanup Script
# Removes all containers, volumes, and images for fresh start
# =============================================================================

param(
    [switch]$Force,
    [switch]$KeepImages
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Bubble Docker Cleanup Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Confirm unless -Force
if (-not $Force) {
    $confirm = Read-Host "This will remove ALL Bubble containers, volumes, and data. Continue? (y/N)"
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

# Stop and remove containers
Write-Host "`n[1/5] Stopping Bubble containers..." -ForegroundColor Yellow
docker-compose down --remove-orphans 2>$null

# Remove specific Bubble containers if still running
Write-Host "`n[2/5] Removing any remaining Bubble containers..." -ForegroundColor Yellow
$containers = @("bubble_web", "bubble_celery", "bubble_nginx", "bubble_postgres", "bubble_redis", "bubble_mlflow", "bubble_tigergraph")
foreach ($container in $containers) {
    docker rm -f $container 2>$null
}

# Remove volumes
Write-Host "`n[3/5] Removing Bubble volumes..." -ForegroundColor Yellow
$volumes = @("bubble_postgres_data", "bubble_redis_data", "bubble_mlruns_data", "bubble_tigergraph_data")
foreach ($volume in $volumes) {
    docker volume rm $volume 2>$null
}

# Prune dangling volumes
Write-Host "`n[4/5] Pruning dangling volumes..." -ForegroundColor Yellow
docker volume prune -f

# Remove images (optional)
if (-not $KeepImages) {
    Write-Host "`n[5/5] Removing Bubble images..." -ForegroundColor Yellow
    $images = @("bubble-web", "bubble-celery")
    foreach ($image in $images) {
        docker rmi $image 2>$null
    }
    # Prune dangling images
    docker image prune -f
} else {
    Write-Host "`n[5/5] Keeping images (--KeepImages specified)" -ForegroundColor Gray
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  Cleanup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "To rebuild and start fresh:" -ForegroundColor Cyan
Write-Host "  docker-compose up -d --build" -ForegroundColor White
Write-Host ""
