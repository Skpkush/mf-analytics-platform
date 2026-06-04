# Repack PBIX using .NET System.IO.Compression in CREATE mode with controlled
# entry order. DataModel is written LAST (PBIX readers stream it from the end)
# and STORED (NoCompression), exactly like the original. All other entries keep
# original order; old page-1 visuals are dropped, new ones inserted before DataModel.

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root     = "C:\Data science\Project\mf-analytics-platform\powerbi"
$backup   = Join-Path $root "mf_analytics_dashboard.bak.pbix"
$out      = Join-Path $root "mf_analytics_dashboard_p1.pbix"
$stage    = Join-Path $root "_p1_stage"
$pagePath = "Report/definition/pages/b5a4a9ec836108a694af/visuals"

if (Test-Path $out) { Remove-Item $out -Force }

$deleteIds = Get-Content (Join-Path $stage "_delete_ids.txt") | Where-Object { $_ -ne "" }
$newIds    = Get-Content (Join-Path $stage "_new_ids.txt")    | Where-Object { $_ -ne "" }
$deleteSet = @{}
foreach ($id in $deleteIds) { $deleteSet["$pagePath/$id/visual.json"] = $true }

$src = [System.IO.Compression.ZipFile]::Open($backup, [System.IO.Compression.ZipArchiveMode]::Read)
$dst = [System.IO.Compression.ZipFile]::Open($out,    [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $dataModelEntry = $null

    # 1. Copy all original entries in order, except old visuals and DataModel (held for last)
    foreach ($entry in $src.Entries) {
        if ($entry.FullName -eq "DataModel") { $dataModelEntry = $entry; continue }
        if ($deleteSet.ContainsKey($entry.FullName)) { continue }

        $level = [System.IO.Compression.CompressionLevel]::Optimal
        $newEntry = $dst.CreateEntry($entry.FullName, $level)
        $inStream  = $entry.Open()
        $outStream = $newEntry.Open()
        try { $inStream.CopyTo($outStream) }
        finally { $outStream.Dispose(); $inStream.Dispose() }
    }

    # 2. Write the 16 new visual entries (before DataModel)
    foreach ($id in $newIds) {
        $srcFile   = Join-Path $stage "$id\visual.json"
        $entryName = "$pagePath/$id/visual.json"
        $newEntry  = $dst.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $writer = New-Object System.IO.StreamWriter($newEntry.Open())
        try { $writer.Write((Get-Content -Raw -Encoding UTF8 $srcFile)) }
        finally { $writer.Dispose() }
    }

    # 3. Write DataModel LAST, STORED (NoCompression) — matches original
    $dmEntry = $dst.CreateEntry("DataModel", [System.IO.Compression.CompressionLevel]::NoCompression)
    $inStream  = $dataModelEntry.Open()
    $outStream = $dmEntry.Open()
    try { $inStream.CopyTo($outStream) }
    finally { $outStream.Dispose(); $inStream.Dispose() }
}
finally {
    $dst.Dispose()
    $src.Dispose()
}

Write-Host "Repacked (DataModel last, STORED): $out"
Write-Host "Size: $([math]::Round((Get-Item $out).Length/1MB,2)) MB"
