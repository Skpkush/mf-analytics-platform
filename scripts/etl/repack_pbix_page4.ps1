# Repack PBIX for Page 4 (Risk & Volatility) — adds a NEW page.
# Source = mf_analytics_dashboard_p3.pbix (keeps Pages 1-3 + DataModel).
# DataModel written LAST and STORED; pages.json replaced to register the new
# page; SecurityBindings dropped + [Content_Types].xml patched.
# Output is a separate file so it does not collide with an open Power BI Desktop.

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root      = "C:\Data science\Project\mf-analytics-platform\powerbi"
$source    = Join-Path $root "mf_analytics_dashboard_p3.pbix"
$out       = Join-Path $root "mf_analytics_dashboard_p4.pbix"
$stage     = Join-Path $root "_p4_stage"
$pageId    = Get-Content (Join-Path $stage "_page_id.txt") | Select-Object -First 1
$pagePath  = "Report/definition/pages/$pageId/visuals"
$pageJson  = "Report/definition/pages/$pageId/page.json"
$pagesJson = "Report/definition/pages/pages.json"

if (Test-Path $out) { Remove-Item $out -Force }

$newIds = Get-Content (Join-Path $stage "_new_ids.txt") | Where-Object { $_ -ne "" }

$src = [System.IO.Compression.ZipFile]::Open($source, [System.IO.Compression.ZipArchiveMode]::Read)
$dst = [System.IO.Compression.ZipFile]::Open($out,    [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $dataModelEntry = $null

    foreach ($entry in $src.Entries) {
        if ($entry.FullName -eq "DataModel") { $dataModelEntry = $entry; continue }
        if ($entry.FullName -eq "SecurityBindings") { continue }
        if ($entry.FullName -eq "[Content_Types].xml") { continue }
        if ($entry.FullName -eq $pagesJson) { continue }

        $newEntry  = $dst.CreateEntry($entry.FullName, [System.IO.Compression.CompressionLevel]::Optimal)
        $inStream  = $entry.Open()
        $outStream = $newEntry.Open()
        try { $inStream.CopyTo($outStream) }
        finally { $outStream.Dispose(); $inStream.Dispose() }
    }

    $ctEntry  = $dst.CreateEntry("[Content_Types].xml", [System.IO.Compression.CompressionLevel]::Optimal)
    $ctBytes  = [System.IO.File]::ReadAllBytes((Join-Path $stage "content_types.xml"))
    $ctStream = $ctEntry.Open()
    try { $ctStream.Write($ctBytes, 0, $ctBytes.Length) }
    finally { $ctStream.Dispose() }

    $pgEntry = $dst.CreateEntry($pagesJson, [System.IO.Compression.CompressionLevel]::Optimal)
    $w = New-Object System.IO.StreamWriter($pgEntry.Open())
    try { $w.Write((Get-Content -Raw -Encoding UTF8 (Join-Path $stage "pages.json"))) }
    finally { $w.Dispose() }

    $pageEntry = $dst.CreateEntry($pageJson, [System.IO.Compression.CompressionLevel]::Optimal)
    $w = New-Object System.IO.StreamWriter($pageEntry.Open())
    try { $w.Write((Get-Content -Raw -Encoding UTF8 (Join-Path $stage "page.json"))) }
    finally { $w.Dispose() }

    foreach ($id in $newIds) {
        $srcFile   = Join-Path $stage "$id\visual.json"
        $entryName = "$pagePath/$id/visual.json"
        $ne = $dst.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $w  = New-Object System.IO.StreamWriter($ne.Open())
        try { $w.Write((Get-Content -Raw -Encoding UTF8 $srcFile)) }
        finally { $w.Dispose() }
    }

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

Write-Host "Repacked Page 4 (DataModel last, STORED): $out"
Write-Host "Size: $([math]::Round((Get-Item $out).Length/1MB,2)) MB"
