# Repack PBIX for Page 2 (Fund Performance).
# Source = current mf_analytics_dashboard.pbix (keeps Page 1 visuals + DataModel).
# - DataModel written LAST and STORED (NoCompression), as PBIX readers expect.
# - Page 2 page.json replaced with the upgraded 1440x900 version.
# - Old Page 2 visuals (if any) dropped; new ones inserted before DataModel.
# Output is a separate file so it does not collide with an open Power BI Desktop.

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root     = "C:\Data science\Project\mf-analytics-platform\powerbi"
$source   = Join-Path $root "mf_analytics_dashboard.pbix"
$out      = Join-Path $root "mf_analytics_dashboard_p2.pbix"
$stage    = Join-Path $root "_p2_stage"
$pageId   = "1f14492bb3a11526ba5f"
$pagePath = "Report/definition/pages/$pageId/visuals"
$pageJson = "Report/definition/pages/$pageId/page.json"

if (Test-Path $out) { Remove-Item $out -Force }

$deleteIds = Get-Content (Join-Path $stage "_delete_ids.txt") | Where-Object { $_ -ne "" }
$newIds    = Get-Content (Join-Path $stage "_new_ids.txt")    | Where-Object { $_ -ne "" }
$deleteSet = @{}
foreach ($id in $deleteIds) { $deleteSet["$pagePath/$id/visual.json"] = $true }

$src = [System.IO.Compression.ZipFile]::Open($source, [System.IO.Compression.ZipArchiveMode]::Read)
$dst = [System.IO.Compression.ZipFile]::Open($out,    [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $dataModelEntry = $null

    foreach ($entry in $src.Entries) {
        if ($entry.FullName -eq "DataModel") { $dataModelEntry = $entry; continue }
        if ($entry.FullName -eq "SecurityBindings") { continue }      # signature invalidated by edits
        if ($entry.FullName -eq "[Content_Types].xml") { continue }   # replaced below (drops SecurityBindings override)
        if ($deleteSet.ContainsKey($entry.FullName)) { continue }
        if ($entry.FullName -eq $pageJson) { continue }               # replaced below

        $newEntry  = $dst.CreateEntry($entry.FullName, [System.IO.Compression.CompressionLevel]::Optimal)
        $inStream  = $entry.Open()
        $outStream = $newEntry.Open()
        try { $inStream.CopyTo($outStream) }
        finally { $outStream.Dispose(); $inStream.Dispose() }
    }

    # Patched [Content_Types].xml (SecurityBindings override removed) — written as raw bytes to preserve BOM
    $ctEntry = $dst.CreateEntry("[Content_Types].xml", [System.IO.Compression.CompressionLevel]::Optimal)
    $ctBytes = [System.IO.File]::ReadAllBytes((Join-Path $stage "content_types.xml"))
    $ctStream = $ctEntry.Open()
    try { $ctStream.Write($ctBytes, 0, $ctBytes.Length) }
    finally { $ctStream.Dispose() }

    # Upgraded Page 2 page.json
    $pageEntry = $dst.CreateEntry($pageJson, [System.IO.Compression.CompressionLevel]::Optimal)
    $w = New-Object System.IO.StreamWriter($pageEntry.Open())
    try { $w.Write((Get-Content -Raw -Encoding UTF8 (Join-Path $stage "page.json"))) }
    finally { $w.Dispose() }

    # New Page 2 visuals
    foreach ($id in $newIds) {
        $srcFile   = Join-Path $stage "$id\visual.json"
        $entryName = "$pagePath/$id/visual.json"
        $ne = $dst.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $w  = New-Object System.IO.StreamWriter($ne.Open())
        try { $w.Write((Get-Content -Raw -Encoding UTF8 $srcFile)) }
        finally { $w.Dispose() }
    }

    # DataModel LAST, STORED
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

Write-Host "Repacked Page 2 (DataModel last, STORED): $out"
Write-Host "Size: $([math]::Round((Get-Item $out).Length/1MB,2)) MB"
