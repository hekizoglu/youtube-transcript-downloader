# ==============================================================================
# YouTube Transkript Indirici - TEK KOMUTLA KURULUM
#
# PowerShell'e yapistirin:
#   irm https://raw.githubusercontent.com/hekizoglu/youtube-transcript-downloader/main/kurulum.ps1 | iex
#
# Yaptiklari: Python, Git ve Deno'yu kurar (yoksa), projeyi indirir veya
# gunceller, Python bagimliliklarini kurar, masaustu + Baslat menusu
# kisayolu olusturur ve uygulamayi acar. Tekrar calistirmak guvenlidir
# (guncelleme olarak calisir).
# ==============================================================================

# Not: "Stop" kullanilmiyor; PowerShell 5.1 git/pip gibi programlarin
# normal stderr ciktisini hata sanabiliyor. Hatalar $LASTEXITCODE ile kontrol edilir.
$ErrorActionPreference = "Continue"
$RepoUrl    = "https://github.com/hekizoglu/youtube-transcript-downloader.git"
$InstallDir = Join-Path $HOME "youtube-transcript-downloader"
$AppName    = "YouTube Transkript"

function Adim($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Tamam($msg) { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Uyari($msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }

function Yenile-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Python-Bul {
    # Microsoft Store'un sahte 'python' kisayolunu (WindowsApps) atla
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 --version *> $null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3") }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue |
           Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1
    if ($cmd) { return @($cmd.Source) }
    $yerel = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if ($yerel) { return @($yerel.FullName) }
    return $null
}

function Winget-Kur($id, $ad) {
    Write-Host "    $ad kuruluyor (birkac dakika surebilir)..."
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements --scope user *> $null
    if ($LASTEXITCODE -ne 0) {
        # Bazi paketler kullanici kapsamini desteklemez, genel kurulumu dene
        winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements *> $null
    }
    Yenile-Path
}

Write-Host "=====================================================" -ForegroundColor Magenta
Write-Host "   YouTube Transkript Indirici - Otomatik Kurulum" -ForegroundColor Magenta
Write-Host "=====================================================" -ForegroundColor Magenta

try {
    # 0. winget
    Adim "winget kontrol ediliyor"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget bulunamadi. Microsoft Store'dan 'Uygulama Yukleyici' (App Installer) kurup tekrar deneyin."
    }
    Tamam "winget hazir"

    # 1. Python
    Adim "Python kontrol ediliyor"
    $Py = Python-Bul
    if (-not $Py) {
        Winget-Kur "Python.Python.3.12" "Python 3.12"
        $Py = Python-Bul
        if (-not $Py) { throw "Python kurulamadi. https://www.python.org/downloads/ adresinden elle kurun." }
    }
    $PyExe = $Py[0]; $PyArgs = @($Py | Select-Object -Skip 1)
    Tamam ((& $PyExe @PyArgs --version) 2>&1)

    # 2. Git
    Adim "Git kontrol ediliyor"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Winget-Kur "Git.Git" "Git"
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            $gitYol = "$env:ProgramFiles\Git\cmd"
            if (Test-Path "$gitYol\git.exe") { $env:Path += ";$gitYol" }
            else { throw "Git kurulamadi." }
        }
    }
    Tamam "Git hazir"

    # 3. Deno (yt-dlp'nin YouTube'dan tam veri alabilmesi icin, istege bagli)
    Adim "Deno kontrol ediliyor (istege bagli)"
    if (-not (Get-Command deno -ErrorAction SilentlyContinue)) {
        try { Winget-Kur "DenoLand.Deno" "Deno" } catch { }
    }
    if (Get-Command deno -ErrorAction SilentlyContinue) { Tamam "Deno hazir" }
    else { Uyari "Deno kurulamadi; uygulama yine calisir, sadece bazi videolarda altyazi bulunamayabilir." }

    # 4. Projeyi indir / guncelle
    Adim "Proje indiriliyor: $InstallDir"
    if (Test-Path (Join-Path $InstallDir ".git")) {
        git -C $InstallDir pull --ff-only --quiet
        if ($LASTEXITCODE -ne 0) { Uyari "Guncelleme yapilamadi (yerel degisiklik olabilir). Mevcut surumle devam ediliyor." }
        else { Tamam "Proje guncellendi" }
    } elseif (Test-Path $InstallDir) {
        throw "$InstallDir klasoru var ama git deposu degil. Klasoru silip veya yeniden adlandirip tekrar deneyin."
    } else {
        git clone --depth 1 --quiet $RepoUrl $InstallDir
        if ($LASTEXITCODE -ne 0) { throw "Proje indirilemedi." }
        Tamam "Proje indirildi"
    }

    # 5. Python bagimliliklari
    Adim "Python bagimliliklari kuruluyor (yt-dlp)"
    & $PyExe @PyArgs -m pip install --upgrade --quiet --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Bagimliliklar kurulamadi." }
    Tamam "Bagimliliklar kuruldu"

    # 6. Kisayollar
    Adim "Kisayollar olusturuluyor"
    $hedef = Join-Path $InstallDir "baslat.bat"
    $ws = New-Object -ComObject WScript.Shell
    $konumlar = @(
        [Environment]::GetFolderPath("Desktop"),
        [Environment]::GetFolderPath("Programs")
    )
    foreach ($klasor in $konumlar) {
        $lnk = $ws.CreateShortcut((Join-Path $klasor "$AppName.lnk"))
        $lnk.TargetPath = $hedef
        $lnk.WorkingDirectory = $InstallDir
        $lnk.Description = "YouTube Toplu Transkript Indirici"
        $lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,18"
        $lnk.Save()
    }
    Tamam "Masaustu ve Baslat menusune '$AppName' kisayolu eklendi"

    Write-Host "`n=====================================================" -ForegroundColor Green
    Write-Host "   KURULUM TAMAMLANDI! Uygulama aciliyor..." -ForegroundColor Green
    Write-Host "   Sonraki seferlerde masaustundeki '$AppName' kisayoluna tiklayin." -ForegroundColor Green
    Write-Host "=====================================================" -ForegroundColor Green
    Start-Process -FilePath $hedef -WorkingDirectory $InstallDir
}
catch {
    Write-Host "`n[HATA] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Sorun devam ederse bu ekranin goruntusunu paylasin." -ForegroundColor Red
}
