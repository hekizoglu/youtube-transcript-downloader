# ==============================================================================
# YOUTUBE KANAL TOPLU TRANSKRİPT İNDİRİCİ (TÜM VİDEOLAR + CANLI YAYINLAR)
# ==============================================================================

$ErrorActionPreference = "Continue"

# UTF-8 Desteğini zorla
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Add-Type -AssemblyName Microsoft.VisualBasic
Add-Type -AssemblyName System.Windows.Forms

function Show-Message {
    param([string]$Message, [string]$Title = "Bilgi", [string]$Icon = "Information")
    [System.Windows.Forms.MessageBox]::Show($Message, $Title, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::$Icon) | Out-Null
}

function Format-Timestamp {
    param([string]$RawTs)
    $Parts = $RawTs -split ":"
    if ($Parts.Count -eq 3) {
        $H = $Parts[0]
        $M = $Parts[1]
        $S = ($Parts[2] -split "\.")[0]
        if ($H -eq "00") { return "$M`:$S" }
        return "$H`:$M`:$S"
    }
    return $RawTs
}

# 1. ADIM: yt-dlp KONTROLÜ
$LocalYtDlp = "$PSScriptRoot\yt-dlp.exe"
$WinGetYtDlp = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\yt-dlp.exe"

if (Get-Command "yt-dlp" -ErrorAction SilentlyContinue) {
    $YtDlpCmd = "yt-dlp"
} elseif (Test-Path $LocalYtDlp) {
    $YtDlpCmd = $LocalYtDlp
} elseif (Test-Path $WinGetYtDlp) {
    $YtDlpCmd = $WinGetYtDlp
} else {
    $cevap = [System.Windows.Forms.MessageBox]::Show(
        "Sistemde 'yt-dlp' aracı bulunamadı. Otomatik olarak indirilsin mi?",
        "Gerekli Araç Eksik",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($cevap -eq "Yes") {
        try {
            Write-Host "yt-dlp indiriliyor, lütfen bekleyin..." -ForegroundColor Cyan
            $TargetFile = "$env:TEMP\yt-dlp.exe"
            Invoke-WebRequest -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile $TargetFile -UseBasicParsing
            $YtDlpCmd = $TargetFile
            Write-Host "yt-dlp başarıyla hazırlandı!" -ForegroundColor Green
        } catch {
            Show-Message "yt-dlp indirilemedi. İnternet bağlantınızı kontrol edin.`nHata: $_" "Kritik Hata" "Error"
            exit
        }
    } else {
        exit
    }
}

# 2. ADIM: KANAL / VİDEO LİNKİ ALMA
$ChannelUrl = [Microsoft.VisualBasic.Interaction]::InputBox(
    "Transkriptlerini indirmek istediğiniz YouTube kanalı, oynatma listesi veya video linkini girin:`n(Örn: @kemalpasabelediyesi)",
    "1. Adım: YouTube Linki",
    "@kemalpasabelediyesi"
)

if ([string]::IsNullOrWhiteSpace($ChannelUrl)) {
    Show-Message "Geçerli bir link girilmedi. İşlem iptal edildi." "İptal" "Warning"
    exit
}

$SubLangs = [Microsoft.VisualBasic.Interaction]::InputBox(
    "İndirilecek altyazı dil kodlarını virgülle ayırarak girin:`n(Örn: tr,en veya sadece tr)",
    "2. Adım: Altyazı Dili",
    "tr,en"
)
if ([string]::IsNullOrWhiteSpace($SubLangs)) { $SubLangs = "tr,en" }

# 3. ADIM: KAYIT KLASÖRÜ
$OutputDir = Join-Path $PSScriptRoot "transkriptler"
if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }

# 4. ADIM: TÜM VİDEOLARI LİSTELEME (/videos, /streams, /shorts)
Write-Host "`nYouTube taranıyor (Normal Videolar + Canlı Yayınlar)... Lütfen bekleyin..." -ForegroundColor Yellow

$ScanUrls = @()
if ($ChannelUrl -match "playlist\?list=" -or $ChannelUrl -match "watch\?v=" -or $ChannelUrl -match "youtu\.be/") {
    $ScanUrls += $ChannelUrl
} else {
    $Base = $ChannelUrl.TrimEnd('/')
    if ($Base.StartsWith("@")) { $Base = "https://www.youtube.com/$Base" }
    elseif (-not $Base.StartsWith("http")) { $Base = "https://www.youtube.com/@$Base" }
    $Base = $Base -replace "/(videos|streams|shorts|featured)$", ""
    
    $ScanUrls += "$Base/videos"
    $ScanUrls += "$Base/streams"
    $ScanUrls += "$Base/shorts"
}

$VideoList = @()
$SeenIds = New-Object System.Collections.Generic.HashSet[string]
$Index = 1

foreach ($ScanTarget in $ScanUrls) {
    $RawVideos = & $YtDlpCmd --flat-playlist --print "%(id)s|%(title)s|%(duration_string)s" --no-warnings --ignore-errors $ScanTarget 2>$null
    if ($RawVideos) {
        foreach ($Line in $RawVideos) {
            $Parts = $Line -split "\|", 3
            if ($Parts.Count -ge 2 -and -not [string]::IsNullOrWhiteSpace($Parts[0])) {
                $VidId = $Parts[0]
                if (-not $SeenIds.Contains($VidId)) {
                    $SeenIds.Add($VidId) | Out-Null
                    $VideoList += [PSCustomObject]@{
                        Sira   = $Index
                        Baslik = $Parts[1]
                        Sure   = if ($Parts.Count -ge 3 -and $Parts[2] -and $Parts[2] -ne "NA") { $Parts[2] } else { "Bilinmiyor" }
                        ID     = $VidId
                        Link   = "https://www.youtube.com/watch?v=$VidId"
                    }
                    $Index++
                }
            }
        }
    }
}

if ($VideoList.Count -eq 0) {
    Show-Message "Videolar listelenemedi! Linki kontrol edin veya videoların erişilebilir olduğundan emin olun." "Hata" "Error"
    exit
}

Write-Host "Toplam $($VideoList.Count) video bulundu (Normal + Canlı Yayın Kayıtları)." -ForegroundColor Green

# 5. ADIM: VİDEO SEÇİMİ (Arama kutusu ile meclis vb. filtrelenebilir)
if ($VideoList.Count -eq 1) {
    $SelectedVideos = $VideoList
} else {
    $SelectedVideos = $VideoList | Out-GridView -Title "İndirmek istediğiniz videoları seçin. Sağ üstteki arama kutusuna 'meclis' yazıp sadece toplantıları seçebilirsiniz. (Tümü için CTRL+A)" -PassThru
}

if (-not $SelectedVideos) {
    Show-Message "Hiçbir video seçilmedi. İşlem sonlandırıldı." "Bilgi" "Information"
    exit
}

# 6. ADIM: İNDİRME VE ZAMAN DAMGALI TEMİZLEME
$SuccessCount = 0
$TotalSelected = @($SelectedVideos).Count
$Current = 0
$LangList = $SubLangs -split ","

Write-Host "`nSeçilen $TotalSelected video için zaman damgalı transkript indirme işlemi başlıyor...`n" -ForegroundColor Cyan

foreach ($Video in $SelectedVideos) {
    $Current++
    $SafeTitle = $Video.Baslik -replace '[\\/:*?"<>|]', '_'
    if ($SafeTitle.Length -gt 80) { $SafeTitle = $SafeTitle.Substring(0, 80) }
    $BaseFileName = ("{0:D3}_{1}" -f $Video.Sira, $SafeTitle)

    Write-Host "[$Current/$TotalSelected] İşleniyor: $($Video.Baslik)" -ForegroundColor White

    $Downloaded = $false

    foreach ($Lang in $LangList) {
        $Lang = $Lang.Trim()
        $TempPrefix = "temp_$($Video.ID)_$Lang"
        Get-ChildItem -Path $OutputDir -Filter "$TempPrefix*.vtt" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

        $OutputTemplate = Join-Path $OutputDir "$TempPrefix.%(ext)s"
        
        $ProcessArgs = @(
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", $Lang,
            "--sub-format", "vtt",
            "--no-warnings",
            "--ignore-errors",
            "-o", $OutputTemplate,
            $Video.Link
        )

        & $YtDlpCmd $ProcessArgs 2>$null | Out-Null

        $VttFiles = Get-ChildItem -Path $OutputDir -Filter "$TempPrefix*.vtt" -ErrorAction SilentlyContinue

        if ($VttFiles) {
            foreach ($Vtt in $VttFiles) {
                $Lines = Get-Content -Path $Vtt.FullName -Encoding UTF8
                $CleanLines = New-Object System.Collections.Generic.List[string]
                $LastLine = ""
                $CurrentTs = "00:00"

                foreach ($L in $Lines) {
                    $Trimmed = $L.Trim()
                    if ($Trimmed -eq "" -or $Trimmed -match "^WEBVTT" -or $Trimmed -match "^Kind:" -or $Trimmed -match "^Language:") {
                        continue
                    }

                    if ($Trimmed -match "^(\d{2}:\d{2}(?::\d{2})?)") {
                        $CurrentTs = Format-Timestamp $Matches[1]
                        continue
                    }

                    if ($Trimmed -match "^\d+$" -or $Trimmed -match "^align:" -or $Trimmed -match "-->") {
                        continue
                    }

                    $NoTags = $Trimmed -replace "<[^>]+>", ""
                    $NoTags = $NoTags.Trim()

                    if ($NoTags -eq "" -or $NoTags -eq $LastLine) { continue }

                    if ($LastLine -and $NoTags.StartsWith($LastLine)) {
                        if ($CleanLines.Count -gt 0) {
                            $CleanLines[$CleanLines.Count - 1] = "[$CurrentTs] $NoTags"
                        } else {
                            $CleanLines.Add("[$CurrentTs] $NoTags")
                        }
                        $LastLine = $NoTags
                        continue
                    }

                    $CleanLines.Add("[$CurrentTs] $NoTags")
                    $LastLine = $NoTags
                }

                $TxtPath = Join-Path $OutputDir "$BaseFileName.txt"
                $Header = "Video Başlığı: $($Video.Baslik)`r`nVideo Linki: $($Video.Link)`r`nDil: $($Lang.ToUpper())`r`nFormat: Zaman Damgalı`r`n============================================================`r`n`r`n"
                $FullText = $Header + ($CleanLines -join "`r`n")
                
                [System.IO.File]::WriteAllText($TxtPath, $FullText, [System.Text.Encoding]::UTF8)
                Remove-Item -Path $Vtt.FullName -Force -ErrorAction SilentlyContinue
            }

            Write-Host "   -> BAŞARILI (Zaman Damgalı - Dil: $Lang)" -ForegroundColor Green
            $Downloaded = $true
            $SuccessCount++
            break
        }
    }

    if (-not $Downloaded) {
        Write-Host "   -> Altyazı bulunamadı." -ForegroundColor DarkYellow
    }

    Start-Sleep -Milliseconds 600
}

Write-Host "`nİşlem Tamamlandı! ($SuccessCount / $TotalSelected başarılı)" -ForegroundColor Cyan
Show-Message "İşlem Tamamlandı!`n`nToplam: $TotalSelected`nBaşarılı: $SuccessCount`nKlasör: $OutputDir" "Tamamlandı" "Information"

Invoke-Item $OutputDir
