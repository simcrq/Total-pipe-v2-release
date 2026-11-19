param(
  [Parameter(Mandatory=$true)][string]$Pptx,
  [Parameter(Mandatory=$true)][string]$Pdf,
  [Parameter(Mandatory=$true)][string]$PngDir
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path (Split-Path $Pdf) | Out-Null
New-Item -ItemType Directory -Force -Path $PngDir | Out-Null
$ppt = New-Object -ComObject PowerPoint.Application
try {
  $pres = $ppt.Presentations.Open($Pptx, $true, $false, $false)
  try {
    $pres.SaveAs($Pdf, 32)
  } finally {
    $pres.Close()
  }
} finally {
  $ppt.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
Get-ChildItem $PngDir -Filter '*.png' -ErrorAction SilentlyContinue | Remove-Item -Force
& pdftoppm -png -r 150 $Pdf (Join-Path $PngDir 'P')
$pages = Get-ChildItem $PngDir -Filter 'P-*.png' | Sort-Object Name
$i = 1
foreach ($f in $pages) {
  $dest = Join-Path $PngDir ("P{0}.png" -f $i)
  Move-Item -LiteralPath $f.FullName -Destination $dest -Force
  $i++
}
Write-Output "rendered $($i-1) pages to $PngDir"
