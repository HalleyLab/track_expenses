param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,

    [string]$LanguageTags = "zh-Hans-CN,en-US"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

function Await-Operation($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethodDefinition -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1

    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$resolvedPath = (Resolve-Path -LiteralPath $ImagePath).Path
$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolvedPath)) ([Windows.Storage.StorageFile])
$stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

function New-OcrEngine([string]$LanguageTag) {
    $language = [Windows.Globalization.Language]::new($LanguageTag)
    if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($language)) {
        return [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    }
    return $null
}

$results = @()
$tags = $LanguageTags -split "," |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ }

foreach ($tag in $tags) {
    try {
        $engine = New-OcrEngine $tag
        if ($null -eq $engine) {
            continue
        }

        $result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        if (-not [string]::IsNullOrWhiteSpace($result.Text)) {
            $results += [pscustomobject]@{
                language = $tag
                text = $result.Text.Trim()
            }
        }
    }
    catch {
        continue
    }
}

if ($results.Count -eq 0) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        throw "Windows OCR is not available for the requested languages."
    }

    $result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    if (-not [string]::IsNullOrWhiteSpace($result.Text)) {
        $results += [pscustomobject]@{
            language = "user-profile"
            text = $result.Text.Trim()
        }
    }
}

ConvertTo-Json -InputObject $results -Compress
