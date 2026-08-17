# Cut the icon tile out of the generated artwork and render it at the sizes
# Windows asks for. A one-off authoring step: the app only ever loads the
# results, so it keeps its no-dependencies promise.
#
# Run with `& <this file>` from a session that can write to the project.

Add-Type -AssemblyName System.Drawing

$source = Join-Path $env:USERPROFILE 'Downloads\Gemini_Generated_Image_sc0gucsc0gucsc0g.jpg'
$outDir = Join-Path $env:USERPROFILE 'Timelogger\assets'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Measured from the artwork: the rounded tile, without its outer glow.
$cropX = 445; $cropY = 124; $cropSize = 520

$original = [System.Drawing.Image]::FromFile($source)
$tile = New-Object System.Drawing.Bitmap $cropSize, $cropSize
$g = [System.Drawing.Graphics]::FromImage($tile)
$g.DrawImage($original,
    (New-Object System.Drawing.Rectangle 0, 0, $cropSize, $cropSize),
    (New-Object System.Drawing.Rectangle $cropX, $cropY, $cropSize, $cropSize),
    [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()
$original.Dispose()

function Save-Rounded {
    param([System.Drawing.Bitmap]$Tile, [int]$Size, [string]$Destination)

    $bmp = New-Object System.Drawing.Bitmap $Size, $Size,
        ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $gfx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gfx.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

    # Rounded corners, so the icon does not sit on a navy square in the
    # taskbar. Radius matches the tile in the artwork, about 22 per cent.
    $r = [int]($Size * 0.22)
    $shape = New-Object System.Drawing.Drawing2D.GraphicsPath
    $shape.AddArc(0, 0, 2*$r, 2*$r, 180, 90)
    $shape.AddArc($Size - 2*$r - 1, 0, 2*$r, 2*$r, 270, 90)
    $shape.AddArc($Size - 2*$r - 1, $Size - 2*$r - 1, 2*$r, 2*$r, 0, 90)
    $shape.AddArc(0, $Size - 2*$r - 1, 2*$r, 2*$r, 90, 90)
    $shape.CloseFigure()
    $gfx.SetClip($shape)

    $gfx.DrawImage($Tile, (New-Object System.Drawing.Rectangle 0, 0, $Size, $Size))
    $gfx.Dispose()
    $shape.Dispose()

    $bmp.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    "  {0,4}px  {1}" -f $Size, (Split-Path $Destination -Leaf)
}

foreach ($size in 256, 128, 64, 48, 32, 16) {
    Save-Rounded -Tile $tile -Size $size -Destination (Join-Path $outDir "icon-$size.png")
}

# The one the app loads at runtime.
Save-Rounded -Tile $tile -Size 256 -Destination (Join-Path $outDir 'icon.png')

$tile.Dispose()
"written to $outDir"
