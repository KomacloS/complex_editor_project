param(
    [Parameter(Mandatory = $true)]
    [string]$TraceId,

    [Parameter(Mandatory = $false)]
    [string]$TimeUtc,

    [Parameter(Mandatory = $false)]
    [string]$LogRoot = 'C:\CE\logs',

    [Parameter(Mandatory = $true)]
    [string]$OutDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-FileContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $encodings = @(
        @{ Name = 'utf8'; Encoding = [System.Text.Encoding]::UTF8 },
        @{ Name = 'unicode'; Encoding = [System.Text.Encoding]::Unicode },
        @{ Name = 'utf8bom'; Encoding = New-Object System.Text.UTF8Encoding($true) },
        @{ Name = 'default'; Encoding = [System.Text.Encoding]::Default }
    )

    $lastError = $null
    foreach ($enc in $encodings) {
        try {
            $lines = [System.IO.File]::ReadAllLines($Path, $enc.Encoding)
            return [PSCustomObject]@{
                Success  = $true
                Lines    = $lines
                Encoding = $enc.Name
            }
        }
        catch {
            $lastError = $_
        }
    }

    Write-Warning ("Failed to read {0}: {1}" -f $Path, $lastError.Exception.Message)
    return [PSCustomObject]@{
        Success  = $false
        Lines    = @()
        Encoding = $null
        Error    = $lastError.Exception.Message
    }
}

function Get-LineTimestamp {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Line
    )

    if ([string]::IsNullOrWhiteSpace($Line)) {
        return $null
    }

    $patterns = @(
        '\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?',
        '\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}:\d{2}',
        '\d{2}/\d{2}/\d{4}[ T]\d{2}:\d{2}:\d{2}'
    )

    foreach ($pattern in $patterns) {
        $match = [System.Text.RegularExpressions.Regex]::Match($Line, $pattern)
        if ($match.Success) {
            $candidate = $match.Value
            $parsed = [System.DateTimeOffset]::MinValue
            if ([System.DateTimeOffset]::TryParse(
                $candidate,
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal,
                [ref]$parsed
            )) {
                return $parsed
            }
        }
    }

    return $null
}

if (-not (Test-Path -Path $LogRoot -PathType Container)) {
    throw "LogRoot '$LogRoot' does not exist or is not a directory."
}

if (-not (Test-Path -Path $OutDir -PathType Container)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$traceOutputPath = Join-Path -Path $OutDir -ChildPath 'logs_by_trace.txt'
$stackOutputPath = Join-Path -Path $OutDir -ChildPath 'stacktrace.txt'
$manifestPath    = Join-Path -Path $OutDir -ChildPath 'log_manifest.json'

$targetTime = $null
$timeWindowMinutes = 10
if ($TimeUtc) {
    try {
        $targetTime = [System.DateTimeOffset]::Parse($TimeUtc, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AssumeUniversal)
    }
    catch {
        Write-Warning "Unable to parse TimeUtc '$TimeUtc'. Stack trace extraction by timestamp will be skipped."
        $targetTime = $null
    }
}

$logFiles = Get-ChildItem -Path $LogRoot -Recurse -File | Where-Object {
    $nameLower = $_.Name.ToLowerInvariant()
    ($nameLower -match '\.log(\.\w+)?$') -or
    ($nameLower -match '\.txt$') -or
    ($nameLower -match '\.out$')
}

if (-not $logFiles) {
    Write-Warning "No log files found under '$LogRoot'."
    Set-Content -Path $traceOutputPath -Value 'No log files were found.' -Encoding UTF8
    Set-Content -Path $stackOutputPath -Value 'No log files were found.' -Encoding UTF8
    Set-Content -Path $manifestPath -Value '[]' -Encoding UTF8
    Write-Host "Trace ID matches: 0"
    Write-Host "Stack traces captured: 0"
    Write-Host "Output files:"
    Write-Host " - $traceOutputPath"
    Write-Host " - $stackOutputPath"
    Write-Host " - $manifestPath"
    exit 0
}

$traceBuilder = New-Object System.Text.StringBuilder
$stackBuilder = New-Object System.Text.StringBuilder
$manifest = @()

$totalTraceMatches = 0
$totalStackMatches = 0

foreach ($file in $logFiles) {
    $readResult = Read-FileContent -Path $file.FullName
    $manifestEntry = [PSCustomObject]@{
        FilePath        = $file.FullName
        SizeBytes       = $file.Length
        EncodingUsed    = $readResult.Encoding
        TraceMatches    = 0
        StackTraceHits  = 0
        ReadError       = $null
    }

    if (-not $readResult.Success) {
        $manifestEntry.ReadError = $readResult.Error
        $manifest += $manifestEntry
        continue
    }

    $lines = $readResult.Lines
    $lineCount = $lines.Length

    $traceIndices = [System.Collections.Generic.List[int]]::new()

    for ($i = 0; $i -lt $lineCount; $i++) {
        $line = $lines[$i]
        if ($line.IndexOf($TraceId, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $traceIndices.Add($i) | Out-Null
        }
    }

    if ($traceIndices.Count -gt 0) {
        $manifestEntry.TraceMatches = $traceIndices.Count
        foreach ($idx in $traceIndices) {
            $totalTraceMatches++

            $startIndex = [System.Math]::Max(0, $idx - 200)
            $endIndex = [System.Math]::Min($lineCount - 1, $idx + 200)

            $null = $traceBuilder.AppendLine(("===== {0} (Line {1}) =====" -f $file.FullName, $idx + 1))
            for ($j = $startIndex; $j -le $endIndex; $j++) {
                $formattedLine = ("{0,6}: {1}" -f ($j + 1), $lines[$j])
                $null = $traceBuilder.AppendLine($formattedLine)
            }
            $null = $traceBuilder.AppendLine()
        }
    }

    $lineTimestamps = @{}
    if ($targetTime) {
        for ($i = 0; $i -lt $lineCount; $i++) {
            $ts = Get-LineTimestamp -Line $lines[$i]
            if ($ts) {
                $lineTimestamps[$i] = $ts
            }
        }

        for ($i = 0; $i -lt $lineCount; $i++) {
            if ($lines[$i] -match '^Traceback \(most recent call last\):') {
                $withinWindow = $false
                $closestTs = $null

                for ($k = -20; $k -le 20; $k++) {
                    $candidateIndex = $i + $k
                    if ($candidateIndex -lt 0 -or $candidateIndex -ge $lineCount) {
                        continue
                    }

                    if ($lineTimestamps.ContainsKey($candidateIndex)) {
                        $tsValue = $lineTimestamps[$candidateIndex]
                        $diffMinutes = [System.Math]::Abs(($tsValue - $targetTime).TotalMinutes)
                        if ($diffMinutes -le $timeWindowMinutes) {
                            $withinWindow = $true
                            $closestTs = $tsValue
                            break
                        }
                    }
                }

                if ($withinWindow) {
                    $totalStackMatches++
                    $manifestEntry.StackTraceHits++

                    $null = $stackBuilder.AppendLine(("===== {0} (Line {1}) =====" -f $file.FullName, $i + 1))
                    if ($closestTs) {
                        $null = $stackBuilder.AppendLine(("Timestamp: {0:O}" -f $closestTs))
                    }

                    $j = $i
                    while ($j -lt $lineCount) {
                        $lineContent = ("{0,6}: {1}" -f ($j + 1), $lines[$j])
                        $null = $stackBuilder.AppendLine($lineContent)
                        $j++

                        if ($j -ge $lineCount) {
                            break
                        }

                        $nextLine = $lines[$j]
                        if ($nextLine -match '^\s*$') {
                            $null = $stackBuilder.AppendLine(("{0,6}: {1}" -f ($j + 1), $nextLine))
                            $j++
                            break
                        }

                        if ($nextLine -notmatch '^\s' -and $nextLine -notmatch '^\tat ' -and $nextLine -notmatch '^During handling of the above exception') {
                            break
                        }
                    }

                    $null = $stackBuilder.AppendLine()
                }
            }
        }
    }

    $manifest += $manifestEntry
}

if ($totalTraceMatches -eq 0) {
    $null = $traceBuilder.AppendLine("No trace ID matches were found.")
}

if ($totalStackMatches -eq 0) {
    if ($targetTime) {
        $null = $stackBuilder.AppendLine("No Python stack traces found within +/-$timeWindowMinutes minutes of $TimeUtc.")
    }
    else {
        $null = $stackBuilder.AppendLine("Stack trace extraction skipped (no valid TimeUtc provided).")
    }
}

[System.IO.File]::WriteAllText($traceOutputPath, $traceBuilder.ToString(), [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($stackOutputPath, $stackBuilder.ToString(), [System.Text.Encoding]::UTF8)

$manifestJson = $manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, [System.Text.Encoding]::UTF8)

Write-Host ("Trace ID matches: {0}" -f $totalTraceMatches)
Write-Host ("Stack traces captured: {0}" -f $totalStackMatches)
Write-Host "Output files:"
Write-Host (" - {0}" -f $traceOutputPath)
Write-Host (" - {0}" -f $stackOutputPath)
Write-Host (" - {0}" -f $manifestPath)
