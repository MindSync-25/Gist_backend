param(
    [string]$ContainerName = "gist-postgres",
    [string]$DbName = "gist",
    [string]$DbUser = "gist",
    [string]$DbPassword = "gistpass",
    [int]$DbPort = 5432
)

$ErrorActionPreference = "Stop"

function Require-DockerEngine {
    try {
        docker info *> $null
    } catch {
        throw "Docker engine is not ready. Start Docker Desktop first, then run this script again."
    }
}

function Ensure-Container {
    param(
        [string]$Name,
        [string]$User,
        [string]$Password,
        [string]$Database,
        [int]$Port
    )

    $existingId = docker ps -a --filter "name=^${Name}$" --format "{{.ID}}"

    if (-not $existingId) {
        docker run -d `
            --name $Name `
            -e "POSTGRES_USER=$User" `
            -e "POSTGRES_PASSWORD=$Password" `
            -e "POSTGRES_DB=$Database" `
            -p "${Port}:5432" `
            -v gist_pgdata:/var/lib/postgresql/data `
            postgres:16-alpine *> $null
        Write-Host "Created container '$Name'."
    } else {
        docker start $Name *> $null
        Write-Host "Started existing container '$Name'."
    }
}

function Wait-ForPostgres {
    param(
        [string]$Name,
        [string]$User,
        [string]$Database
    )

    for ($i = 0; $i -lt 45; $i++) {
        docker exec $Name pg_isready -U $User -d $Database *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Postgres is ready."
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "Postgres did not become ready in time."
}

function Ensure-ComicsTable {
    param(
        [string]$Name,
        [string]$User,
        [string]$Database
    )

    $createComicsSql = @"
CREATE TABLE IF NOT EXISTS comics (
    id SERIAL PRIMARY KEY,
    article_url TEXT NOT NULL DEFAULT '',
    headline TEXT,
    category TEXT,
    run_date DATE NOT NULL DEFAULT CURRENT_DATE,
    tone TEXT,
    summary TEXT,
    banner_title TEXT,
    scene TEXT,
    hero_character TEXT,
    background TEXT,
    dialogue JSONB,
    image_prompt TEXT,
    s3_key TEXT,
    s3_url TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);
"@

    docker exec -i $Name psql -v ON_ERROR_STOP=1 -U $User -d $Database -c $createComicsSql *> $null
    Write-Host "Ensured prerequisite table 'comics'."
}

function Apply-PlatformSchema {
    param(
        [string]$SchemaPath,
        [string]$Name,
        [string]$User,
        [string]$Database
    )

    Get-Content $SchemaPath -Raw | docker exec -i $Name psql -v ON_ERROR_STOP=1 -U $User -d $Database *> $null
    Write-Host "Applied platform schema."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$schemaFile = Join-Path $repoRoot "app\\db\\001_initial_platform_schema.sql"

if (-not (Test-Path $schemaFile)) {
    throw "Schema file not found: $schemaFile"
}

Require-DockerEngine
Ensure-Container -Name $ContainerName -User $DbUser -Password $DbPassword -Database $DbName -Port $DbPort
Wait-ForPostgres -Name $ContainerName -User $DbUser -Database $DbName
Ensure-ComicsTable -Name $ContainerName -User $DbUser -Database $DbName
Apply-PlatformSchema -SchemaPath $schemaFile -Name $ContainerName -User $DbUser -Database $DbName

Write-Host ""
Write-Host "Local PostgreSQL is ready on localhost:$DbPort"
Write-Host "DB: $DbName | User: $DbUser"