# PostgreSQL Setup Script for WorldBase
# Run this script to initialize PostgreSQL database and migrate from SQLite

param(
    [string]$DatabaseName = "worldbase",
    [string]$Username = "worldbase",
    [string]$Password = "worldbase",
    [string]$AdminUsername = "postgres",
    [string]$AdminPassword = "",  # Empty = will try Windows auth or prompt
    [string]$DbHost = "localhost",
    [int]$Port = 5432,
    [switch]$Migrate,
    [string]$SqlitePath = "..\worldbase.db",
    [switch]$SkipCreate
)

$ErrorActionPreference = "Stop"

Write-Host "=== WorldBase PostgreSQL Setup ===" -ForegroundColor Cyan
Write-Host ""

# Find PostgreSQL client (psql)
$pgSqlPath = $null

# First try PATH
$pgCmd = Get-Command "psql" -ErrorAction SilentlyContinue
if ($pgCmd) {
    $pgSqlPath = $pgCmd.Source
}

# If not in PATH, search common locations
if (-not $pgSqlPath) {
    $searchPaths = @(
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\15\bin\psql.exe",
        "C:\Program Files\PostgreSQL\14\bin\psql.exe",
        "C:\Program Files\PostgreSQL\13\bin\psql.exe",
        "C:\Program Files (x86)\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files (x86)\PostgreSQL\15\bin\psql.exe"
    )
    
    foreach ($path in $searchPaths) {
        if (Test-Path $path) {
            $pgSqlPath = $path
            break
        }
    }
}

# Also search Program Files dynamically
if (-not $pgSqlPath) {
    $pgBaseDirs = @("C:\Program Files\PostgreSQL", "C:\Program Files (x86)\PostgreSQL")
    foreach ($baseDir in $pgBaseDirs) {
        if (Test-Path $baseDir) {
            $versions = Get-ChildItem -Path $baseDir -Directory -ErrorAction SilentlyContinue | 
                        Where-Object { $_.Name -match '^\d+$' } |
                        Sort-Object Name -Descending
            foreach ($ver in $versions) {
                $candidate = Join-Path $ver.FullName "bin\psql.exe"
                if (Test-Path $candidate) {
                    $pgSqlPath = $candidate
                    break
                }
            }
            if ($pgSqlPath) { break }
        }
    }
}

if (-not $pgSqlPath) {
    Write-Host "ERROR: PostgreSQL client (psql) not found." -ForegroundColor Red
    Write-Host "Searched in:" -ForegroundColor Yellow
    Write-Host "  - PATH environment variable"
    Write-Host "  - C:\Program Files\PostgreSQL\<version>\bin"
    Write-Host ""
    Write-Host "Please either:" -ForegroundColor Cyan
    Write-Host "  1. Add PostgreSQL bin folder to PATH:" -ForegroundColor White
    Write-Host "     `$env:PATH += `";C:\Program Files\PostgreSQL\16\bin`"" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  2. Or download and install PostgreSQL:" -ForegroundColor White
    Write-Host "     https://www.postgresql.org/download/windows/" -ForegroundColor Gray
    exit 1
}

Write-Host "PostgreSQL client found: $pgSqlPath" -ForegroundColor Green

# Get admin password if not provided
if (-not $AdminPassword) {
    # Try Windows authentication first (no password)
    Write-Host ""
    Write-Host "Trying Windows authentication..." -ForegroundColor Yellow
    $useWindowsAuth = $true
    
    # We'll set this later if Windows auth fails
} else {
    $useWindowsAuth = $false
}

# Note: We'll pass password via PGPASSWORD environment variable instead of URL
$dbUrl = "postgresql://${Username}:${Password}@${DbHost}:${Port}/${DatabaseName}"
$asyncDbUrl = "postgresql+asyncpg://${Username}:${Password}@${DbHost}:${Port}/${DatabaseName}"

Write-Host ""
Write-Host "Connection info:" -ForegroundColor Cyan
Write-Host "  - Host: ${DbHost}:${Port}" -ForegroundColor Gray
Write-Host "  - Database: ${DatabaseName}" -ForegroundColor Gray
Write-Host "  - User: ${Username}" -ForegroundColor Gray
Write-Host "  - Admin: ${AdminUsername}" -ForegroundColor Gray
if ($useWindowsAuth) {
    Write-Host "  - Auth: Windows/current user" -ForegroundColor Gray
}

if (-not $SkipCreate) {
    Write-Host ""
    Write-Host "Step 1: Creating database and user..." -ForegroundColor Yellow
    
    # Create user SQL (avoid $ for PowerShell escaping)
    $createUserSql = "DO 'BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = ''''${Username}'''') THEN CREATE USER ${Username} WITH PASSWORD ''''${Password}''''; END IF; END;';"
    
    # Alternative simpler approach using psql meta-command
    $checkUserSql = "SELECT 1 FROM pg_roles WHERE rolname='${Username}';"
    $createUserCmd = "CREATE USER ${Username} WITH PASSWORD '${Password}';"    
    
    # Build psql arguments
    $psqlArgs = @()
    if ($useWindowsAuth) {
        $psqlArgs = @("-h", $DbHost, "-p", $Port, "-U", $AdminUsername, "-d", "postgres")
    } else {
        $env:PGPASSWORD = $AdminPassword
        $psqlArgs = @("-h", $DbHost, "-p", $Port, "-U", $AdminUsername, "-d", "postgres")
    }
    
    # Check if user exists first
    try {
        $userExists = & $pgSqlPath @psqlArgs -t -c $checkUserSql 2>&1
        if (-not $userExists.Trim()) {
            & $pgSqlPath @psqlArgs -c $createUserCmd 2>&1 | Out-Null
            Write-Host "  - User '${Username}' created" -ForegroundColor Green
        } else {
            Write-Host "  - User '${Username}' already exists" -ForegroundColor Gray
        }
        
        # Alter user password (in case it was created before)
        & $pgSqlPath @psqlArgs -c "ALTER USER ${Username} WITH PASSWORD '${Password}';" 2>&1 | Out-Null
    } catch {
        Write-Host "WARNING: Could not create user (may require admin privileges): $_" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "If you see 'password authentication failed', you may need to:" -ForegroundColor Cyan
        Write-Host "  1. Set the correct admin password:" -ForegroundColor White
        Write-Host "     .\setup-postgres.ps1 -AdminPassword 'your_postgres_password' -Migrate" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  2. Or create the user manually in pgAdmin/psql:" -ForegroundColor White
        Write-Host "     CREATE USER ${Username} WITH PASSWORD '${Password}';" -ForegroundColor Gray
        Write-Host "     CREATE DATABASE ${DatabaseName} OWNER ${Username};" -ForegroundColor Gray
    }
    
    # Create database
    $dbQuery = "SELECT 1 FROM pg_database WHERE datname = '${DatabaseName}';"
    $dbExists = & $pgSqlPath @psqlArgs -t -c $dbQuery 2>$null
    if (-not $dbExists.Trim()) {
        $createDbSql = "CREATE DATABASE ${DatabaseName} OWNER ${Username};"
        & $pgSqlPath @psqlArgs -c $createDbSql 2>&1 | Out-Null
        Write-Host "  - Database '${DatabaseName}' created" -ForegroundColor Green
    } else {
        Write-Host "  - Database '${DatabaseName}' already exists" -ForegroundColor Gray
    }
    
    # Grant privileges
    $grantSql = "GRANT ALL PRIVILEGES ON DATABASE ${DatabaseName} TO ${Username};"
    & $pgSqlPath @psqlArgs -c $grantSql 2>&1 | Out-Null
    Write-Host "  - Privileges granted" -ForegroundColor Green
}

Write-Host ""
Write-Host "Step 2: Testing connection..." -ForegroundColor Yellow

# Set password for worldbase user connection
$env:PGPASSWORD = $Password

$testArgs = @("-h", $DbHost, "-p", $Port, "-U", $Username, "-d", $DatabaseName)
try {
    $result = & $pgSqlPath @testArgs -c "SELECT version();" 2>&1
    Write-Host "  - Connection successful!" -ForegroundColor Green
    Write-Host "  - $($result[2])" -ForegroundColor Gray
} catch {
    Write-Host "ERROR: Could not connect to database: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 3: Environment Configuration" -ForegroundColor Yellow
Write-Host "Add these lines to your .env file:" -ForegroundColor Cyan
Write-Host ""
Write-Host "# PostgreSQL Configuration"
Write-Host "DATABASE_URL=${asyncDbUrl}"
Write-Host ""

if ($Migrate) {
    Write-Host ""
    Write-Host "Step 4: Running Migration from SQLite..." -ForegroundColor Yellow
    
    $sqliteFullPath = Resolve-Path $SqlitePath -ErrorAction SilentlyContinue
    if (-not $sqliteFullPath) {
        Write-Host "ERROR: SQLite database not found at: $SqlitePath" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "  - Source: $sqliteFullPath" -ForegroundColor Gray
    Write-Host "  - Target: $dbUrl" -ForegroundColor Gray
    Write-Host ""
    
    # Check if migration script exists
    $migrateScript = "..\scripts\migrate_to_postgres.py"
    if (-not (Test-Path $migrateScript)) {
        Write-Host "ERROR: Migration script not found at: $migrateScript" -ForegroundColor Red
        exit 1
    }
    
    # Run migration
    Write-Host "Starting migration (this may take a while)..." -ForegroundColor Yellow
    
    $env:PGPASSWORD = $Password
    python $migrateScript --sqlite-path $sqliteFullPath --postgres-url $dbUrl
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Migration completed successfully!" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "Migration failed with exit code: $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Add DATABASE_URL to your .env file"
Write-Host "  2. Install dependencies: pip install -r requirements.txt"
Write-Host "  3. Test database health: curl http://localhost:8002/api/health"
Write-Host ""

if (-not $Migrate) {
    Write-Host "To migrate existing SQLite data, run:" -ForegroundColor Yellow
    Write-Host "  .\setup-postgres.ps1 -Migrate -SqlitePath '..\worldbase.db'" -ForegroundColor Cyan
}
