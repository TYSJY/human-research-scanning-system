Set-Location $PSScriptRoot

function Get-UsablePython {
    $candidates = @(
        @{Exe='py'; Args=@('-3.13')},
        @{Exe='py'; Args=@('-3.12')},
        @{Exe='py'; Args=@('-3.11')},
        @{Exe='py'; Args=@('-3.10')},
        @{Exe='py'; Args=@()},
        @{Exe='python'; Args=@()}
    )

    foreach ($candidate in $candidates) {
        try {
            & $candidate.Exe @($candidate.Args + @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)')) *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
        }
    }

    return $null
}

$python = if (Test-Path '.venv\Scripts\python.exe') {
    @{Exe=(Join-Path $PSScriptRoot '.venv\Scripts\python.exe'); Args=@()}
} else {
    Get-UsablePython
}

if (-not $python) {
    Write-Host '[ERROR] Cannot find Python 3.10 or newer.' -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host '[INFO] Working directory:' $PSScriptRoot
Write-Host '[INFO] Starting local UI on http://127.0.0.1:8765/'
Write-Host ''

try {
    if ($args.Length -gt 0) {
        & $python.Exe @($python.Args + @('-m', 'research_os.cli', 'ui', $args[0], '--port', '8765'))
        exit $LASTEXITCODE
    }

    $projectsRoot = Join-Path $PSScriptRoot 'projects'
    $hasProject = Test-Path $projectsRoot -PathType Container -and (Get-ChildItem -Path $projectsRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $hasProject) {
        Write-Host '[INFO] No local project detected. Creating a demo project first...'
        & $python.Exe @($python.Args + @('-m', 'research_os.cli', 'quickstart', '--launch-ui', '--port', '8765'))
        exit $LASTEXITCODE
    }

    & $python.Exe @($python.Args + @('-m', 'research_os.cli', 'ui', '--port', '8765'))
    exit $LASTEXITCODE
} catch {
    Write-Host ''
    Write-Host '[ERROR] Launch failed.' -ForegroundColor Red
    Write-Host $_.Exception.Message
    Read-Host 'Press Enter to exit'
    exit 1
}
