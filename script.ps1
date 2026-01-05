# =========================================================================
# Universal GAM Launcher v4.6
# Created by Danny and Lewis
# =========================================================================

# Always run from the script's own directory (PS2EXE-safe)
$scriptDir = $null
try {
    if ($PSScriptRoot) {
        $scriptDir = $PSScriptRoot
    } elseif ($PSCommandPath) {
        $scriptDir = Split-Path -Parent $PSCommandPath
    } elseif ($MyInvocation.MyCommand.Path) {
        $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
} catch {
    # Fall back to exe base directory if anything above fails (e.g., illegal chars from PS2EXE)
    try { $scriptDir = [System.AppDomain]::CurrentDomain.BaseDirectory } catch {}
}
if (-not $scriptDir) {
    try { $scriptDir = [System.AppDomain]::CurrentDomain.BaseDirectory } catch {}
}
if ($scriptDir -and (Test-Path $scriptDir)) {
    Set-Location $scriptDir
}

# ----------------------------
# Configuration paths
# ----------------------------
$ConfigRoot      = "C:\EDUIT\GAM_Configs"
$JsonPath        = Join-Path $ConfigRoot "GAM_Clients.json"
$LogRoot         = "C:\EDUIT\Logs\PowerShell"
$GamTemplatePath = "C:\EDUIT\GAM_Configs\GAM-Template"
$JsonBackupRoot  = "C:\EDUIT\GAM_Configs\GAM-JSONBackups"

# ----------------------------
# Ensure required directories
# ----------------------------
foreach ($dir in @($ConfigRoot, $LogRoot, $JsonBackupRoot)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

# Create JSON if missing
if (-not (Test-Path $JsonPath)) {
    @{ Environments = @() } |
        ConvertTo-Json -Depth 5 |
        Set-Content -Path $JsonPath -Encoding UTF8
}

# Start transcript
function Start-LauncherTranscript {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $logFile = Join-Path $LogRoot "GAMLaunch_$ts.txt"
    Start-Transcript -Path $logFile -Force
}

Start-LauncherTranscript

# =========================================================================
# Helper Functions
# =========================================================================

function Load-GAMJson {
    try {
        $content = Get-Content -Raw -Path $JsonPath | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $content.Environments) {
            $content | Add-Member -Name Environments -Value @() -MemberType NoteProperty
        } elseif (
            $content.Environments -and
            (
                $content.Environments -isnot [System.Collections.IEnumerable] -or
                $content.Environments -is [string] -or
                $content.Environments -is [System.Management.Automation.PSCustomObject] -or
                $content.Environments -is [System.Collections.Hashtable]
            )
        ) {
            # Auto-wrap a single object into an array to keep the launcher happy
            $content.Environments = @($content.Environments)
        }
        return $content
    } catch {
        Write-Host "Error loading JSON: $_" -ForegroundColor Red
        return $null
    }
}

function Save-GAMJson {
    param([Parameter(Mandatory = $true)] $data)

    try {
        if (Test-Path $JsonPath) {
            $backupName = "GAM_Clients_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
            $backupPath = Join-Path $JsonBackupRoot $backupName
            Copy-Item -Path $JsonPath -Destination $backupPath -Force
            Write-Host "JSON backup saved to: $backupPath"
        } else {
            Write-Host "No existing JSON to back up; creating fresh file."
        }
    } catch {
        Write-Host "Warning: could not create JSON backup: $_" -ForegroundColor Yellow
    }

    $data | ConvertTo-Json -Depth 10 | Set-Content -Path $JsonPath -Encoding UTF8
    Write-Host "Saved JSON to: $JsonPath"
}

function Normalise-Path {
    param($p)
    if ($null -eq $p) { return $p }
    $clean = $p.Trim().Trim('"')
    $clean = $clean -replace '/', '\'
    return $clean
}

function GamExe-Exists {
    param([string]$folder)
    return Test-Path (Join-Path $folder "gam.exe")
}

function Set-SwitchFunctions {
    $script:SwitchRequested = $false
    $script:SwitchTarget    = $null

    function global:Switch-GAMEnvironment {
        param([string]$Name)

        $script:SwitchRequested = $true
        if ($Name) {
            $script:SwitchTarget = $Name
        }

        if ($Host.Runspace.IsNested) {
            $Host.ExitNestedPrompt()
        }
    }

    Set-Alias -Name switchenv -Scope Global -Value Switch-GAMEnvironment -Force
    try {
        Set-Alias -Name switch -Scope Global -Value Switch-GAMEnvironment -Force
    } catch {
        Write-Verbose "Could not create 'switch' alias: $_"
    }
}

# =========================================================================
# Create New GAM Environment (AUTO-PATH + AUTO TEMPLATE CLONE)
# =========================================================================

function New-GAMEnvironment {

    Write-Host ""
    Write-Host "Create New GAM Environment"
    Write-Host "-------------------------------------------"

    $name = Read-Host "Enter Environment Name (e.g., WMAT-ROD - Rodborough School)"
    if ([string]::IsNullOrWhiteSpace($name)) {
        Write-Host "Name required."
        return
    }

    # Auto-generate safe folder key
    $safeKey = $name -replace '[^A-Za-z0-9\- ]','' -replace '\s+',''
    $path = "C:\EDUIT\GAM_Configs\GAM-Clients\$safeKey"

    Write-Host "Auto-generated folder:"
    Write-Host "  $path"

    $admin = Read-Host "Enter Google Admin Email (optional)"
    $color = Read-Host "Enter Display Colour (optional)"

    # Load JSON
    $json = Load-GAMJson
    if ($null -eq $json) { return }

    # Duplicate check
    if ($json.Environments | Where-Object { $_.Name -eq $name -or (Normalise-Path $_.Path) -eq $path }) {
        Write-Host "Environment already exists." -ForegroundColor Yellow
        return
    }

    # Create destination
    New-Item -ItemType Directory -Path $path -Force | Out-Null

    # ----------------------------
    # Clone GAM Template
    # ----------------------------

    Write-Host ""
    Write-Host "Using template: $GamTemplatePath"

    $templateSource = $null

    # Case 1: gam.exe directly in template root
    if (Test-Path (Join-Path $GamTemplatePath "gam.exe")) {
        $templateSource = $GamTemplatePath
    } else {
        # Case 2: detect gam.exe in first subfolder (for extracted GAM releases)
        $sub = Get-ChildItem $GamTemplatePath -Directory -ErrorAction SilentlyContinue |
               Where-Object { Test-Path (Join-Path $_.FullName "gam.exe") } |
               Select-Object -First 1
        if ($sub) { $templateSource = $sub.FullName }
    }

    if ($templateSource) {
        Write-Host "Cloning template from: $templateSource"
        try {
            Copy-Item -Path (Join-Path $templateSource "*") -Destination $path -Recurse -Force
        } catch {
            Write-Host "Template copy failed: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "WARNING: No valid GAM template found." -ForegroundColor Yellow
        Write-Host "Expected gam.exe under: $GamTemplatePath"
        Write-Host "Place gam.exe in the new environment manually."
    }

    # ----------------------------
    # Create .gam structure
    # ----------------------------
    $gamDir = Join-Path $path ".gam"
    foreach ($folder in @($gamDir, "$gamDir\gamcache", "$gamDir\drive")) {
        if (-not (Test-Path $folder)) {
            New-Item -ItemType Directory -Path $folder -Force | Out-Null
        }
    }

    # Remove any OAuth creds copied from template
    foreach ($token in @("$gamDir\oauth2.txt", "$gamDir\oauth2service.json")) {
        if (Test-Path $token) {
            Remove-Item -LiteralPath $token -Force -ErrorAction SilentlyContinue
        }
    }

    # ----------------------------
    # Add to JSON
    # ----------------------------
    $json.Environments += [PSCustomObject]@{
        Name  = $name
        Path  = $path
        Admin = $admin
        Color = $color
    }

    Save-GAMJson $json

    Write-Host ""
    Write-Host "Environment created:"
    Write-Host "Name : $name"
    Write-Host "Path : $path"

    if (GamExe-Exists $path) {
        Write-Host "gam.exe detected."
    } else {
        Write-Host "gam.exe NOT found. Add it manually to:"
        Write-Host "  $path"
    }
}

# =========================================================================
# Delete Environment
# =========================================================================

function Delete-GAMEnvironment {
    $json = Load-GAMJson
    if ($null -eq $json) { return }
    if ($json.Environments.Count -eq 0) {
        Write-Host "No environments to delete."
        return
    }

    Write-Host ""
    Write-Host "Delete Environment"
    Write-Host "-------------------------------------------"

    $i = 1
    foreach ($env in $json.Environments) {
        Write-Host "[$i] $($env.Name) - $($env.Path)"
        $i++
    }

    $choiceRaw = Read-Host "Select an environment number to delete (Enter to cancel)"
    if ([string]::IsNullOrWhiteSpace($choiceRaw)) { return }
    $choice = $choiceRaw.Trim()

    if (-not ($choice -as [int]) -or $choice -lt 1 -or $choice -gt $json.Environments.Count) {
        Write-Host "Invalid selection."
        return
    }

    $idx = [int]$choice - 1
    $target = $json.Environments[$idx]

    Write-Host ""
    Write-Host "You are about to delete:"
    Write-Host "Name: $($target.Name)"
    Write-Host "Path: $($target.Path)"
    $confirm = Read-Host "Type YES to confirm"
    if ($confirm -ne "YES") {
        Write-Host "Cancelled."
        return
    }

    $json.Environments = $json.Environments | Where-Object { $_.Name -ne $target.Name }
    Save-GAMJson $json
    Write-Host "Environment removed from configuration."

    $deleteFolder = Read-Host "Delete environment folder on disk? (Y/N)"
    if ($deleteFolder -eq "Y" -and (Test-Path $target.Path)) {
        try {
            Remove-Item -LiteralPath $target.Path -Force -Recurse
            Write-Host "Folder deleted."
        } catch {
            Write-Host "Error deleting folder: $_"
        }
    } else {
        Write-Host "Folder retained."
    }
}

# =========================================================================
# Validate / Sanitise JSON
# =========================================================================

function Validate-And-Sanitise-Json {
    $json = Load-GAMJson
    if ($null -eq $json) { return }

    $issues = @()

    for ($i = 0; $i -lt $json.Environments.Count; $i++) {
        $env   = $json.Environments[$i]
        $orig  = $env.Path
        $clean = Normalise-Path $orig
        if ($orig -ne $clean) {
            $issues += [PSCustomObject]@{
                Index    = $i
                Name     = $env.Name
                Original = $orig
                Clean    = $clean
            }
        }
    }

    if ($issues.Count -eq 0) {
        Write-Host "JSON paths look clean."
        return
    }

    Write-Host ""
    Write-Host "The following path issues were found:"
    foreach ($p in $issues) {
        Write-Host "[$($p.Index + 1)] $($p.Name)"
        Write-Host "  Original: $($p.Original)"
        Write-Host "  Clean   : $($p.Clean)"
        Write-Host ""
    }

    $apply = Read-Host "Apply these fixes now? (Y/N)"
    if ($apply -ne "Y") {
        Write-Host "No changes made."
        return
    }

    foreach ($p in $issues) {
        $json.Environments[$p.Index].Path = $p.Clean
    }

    Save-GAMJson $json
    Write-Host "Sanitisation complete."
}

# =========================================================================
# Show Menu
# =========================================================================

function Show-Menu {

    Clear-Host
    Write-Host "------------------------------------------------------------" -ForegroundColor White
    Write-Host "Universal GAM Launcher v4.6" -ForegroundColor Green
    Write-Host "Created by Danny and Lewis" -ForegroundColor Cyan
    Write-Host "------------------------------------------------------------" -ForegroundColor White
    Write-Host ""

    $json = Load-GAMJson
    if ($null -eq $json) { return $null }

    if ($json.Environments.Count -eq 0) {
        Write-Host "No environments configured."
        Write-Host ""
    } else {
        Write-Host "Configured Environments:"
        $n = 1
        foreach ($env in $json.Environments) {
            Write-Host "[$n] $($env.Name) - $(Normalise-Path $env.Path)"
            $n++
        }
        Write-Host ""
    }

    Write-Host "[N] Create New Environment"
    Write-Host "[D] Delete Existing Environment"
    Write-Host "[V] Validate / Sanitise JSON"
    Write-Host "[Q] Quit"
    Write-Host ""

    return $json
}

# =========================================================================
# Main Loop
# =========================================================================

$script:LauncherCompleted = $false
$script:ExitRequested     = $false
$script:PendingTarget     = $null
$script:SwitchRequested   = $false
$script:SwitchTarget      = $null

:MainLoop while (-not $script:ExitRequested) {

    $script:LauncherCompleted = $false
    $script:SwitchRequested   = $false
    $script:SwitchTarget      = $null
    $currentSwitchTarget      = $script:PendingTarget
    $script:PendingTarget     = $null

    $json = Show-Menu
    if ($null -eq $json) { break }

    $choiceRaw = $null

    if ($currentSwitchTarget) {
        $targetIndex = -1
        for ($i = 0; $i -lt $json.Environments.Count; $i++) {
            if ($json.Environments[$i].Name -ieq $currentSwitchTarget) {
                $targetIndex = $i
                break
            }
        }

        if ($targetIndex -ge 0) {
            $choiceRaw = ($targetIndex + 1).ToString()
            Write-Host "Switching to: $($json.Environments[$targetIndex].Name)" -ForegroundColor Cyan
        } else {
            Write-Host "Requested environment '$currentSwitchTarget' not found. Returning to menu." -ForegroundColor Yellow
        }

        $currentSwitchTarget = $null
    }

    if (-not $choiceRaw) {
        $choiceRaw = Read-Host "Select option"
    }

    if ([string]::IsNullOrWhiteSpace($choiceRaw)) { continue }
    $choice = $choiceRaw.Trim()

    switch -Regex ($choice) {

        '^[Qq]$' { $script:ExitRequested = $true; break }

        '^[Nn]$' { New-GAMEnvironment; continue MainLoop }

        '^[Dd]$' { Delete-GAMEnvironment; continue MainLoop }

        '^[Vv]$' { Validate-And-Sanitise-Json; continue MainLoop }

        '^\d+$' {
            $num = [int]$choice
            if ($num -lt 1 -or $num -gt $json.Environments.Count) {
                Write-Host "Invalid environment."
                continue MainLoop
            }

            $env     = $json.Environments[$num - 1]
            $GAMPath = Normalise-Path $env.Path

            if (-not (Test-Path $GAMPath)) {
                Write-Host "Environment folder does not exist: $GAMPath"
                continue
            }

            $GAMDir    = Join-Path $GAMPath ".gam"
            $GAMConfig = Join-Path $GAMDir "gam.cfg"
            $GAMCache  = Join-Path $GAMDir "gamcache"
            $GAMDrive  = Join-Path $GAMDir "drive"
            $OAuthUser = Join-Path $GAMDir "oauth2.txt"
            $OAuthSvc  = Join-Path $GAMDir "oauth2service.json"

            foreach ($folder in @($GAMPath, $GAMDir, $GAMCache, $GAMDrive)) {
                if (-not (Test-Path $folder)) {
                    New-Item -ItemType Directory -Path $folder -Force | Out-Null
                }
            }

            $env:GAMCFGDIR = $GAMDir
            Write-Host "GAMCFGDIR set to: $GAMDir"

            $gamExe = Join-Path $GAMPath "gam.exe"
            if (Test-Path $gamExe) {
                function Invoke-GamExe {
                    param(
                        [Parameter(ValueFromRemainingArguments = $true)]
                        [string[]]$Args
                    )

                    if ($Args -and $Args[0].ToLower() -eq 'gam') {
                        if ($Args.Count -gt 1) {
                            $Args = $Args[1..($Args.Count - 1)]
                        } else {
                            $Args = @()
                        }
                    }

                    & "$gamExe" @Args
                }

                function global:gam {
                    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)

                    if ($Args -and $Args[0].ToLower() -eq 'gam') {
                        if ($Args.Count -gt 1) {
                            $Args = $Args[1..($Args.Count - 1)]
                        } else {
                            $Args = @()
                        }
                    }

                    Invoke-GamExe @Args
                }

                function Invoke-GamCommand {
                    param(
                        [Parameter(Mandatory = $true)][string]$CommandName,
                        [string[]]$Args
                    )

                    if (-not $Args) {
                        $Args = @()
                    }
                    $cmdArgs = @($CommandName) + $Args
                    Invoke-GamExe @cmdArgs
                }

                $gamCommands = @(
                    'adminrole','alert','alias','browser','building','chatevent','chatmember','chatmessage',
                    'chatspace','chromeapp','chromeprofile','chromeprofilecommand','chromeschema','cigroup',
                    'cigroupmembers','contact','course','courses','cros','crostelemetry','currentprojectid',
                    'customer','datatransfer','device','deviceuser','deviceuserstate','domain','domainalias',
                    'domaincontact','drivefileacl','drivelabel','group','groupmembers','inboundssoassignment',
                    'inboundssocredential','inboundssoprofile','instance','mobile','org','orgs','peoplecontact',
                    'peopleprofile','policy','printer','resoldcustomer','resoldsubscription','resource',
                    'resources','schema','shareddrive','site','siteacl','user','userinvitation','users',
                    'vaultexport','vaulthold','vaultmatter','vaultquery','verify'
                )

                foreach ($cmd in $gamCommands) {
                    $scriptBlock = $ExecutionContext.InvokeCommand.NewScriptBlock(@"
 param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$Args)

 if (`$Args -and `$Args[0].ToLower() -eq 'gam') {
     if (`$Args.Count -gt 1) {
         `$Args = `$Args[1..(`$Args.Count - 1)]
     } else {
         `$Args = @()
     }
 }

 Invoke-GamCommand -CommandName '$cmd' -Args `$Args
"@)

                    Set-Item -Path "function:global:$cmd" -Value $scriptBlock -Force
                }

                Write-Host "Global function 'gam' bound to: $gamExe"
                Write-Host "GAM commands can now be run directly (with or without leading 'gam')"
            } else {
                Write-Host "gam.exe not found in $GAMPath" -ForegroundColor Yellow
                Write-Host "The 'gam' function cannot run until gam.exe is added." -ForegroundColor Yellow
            }

            Set-Location $GAMPath
            Write-Host ""
            Write-Host "Environment active: $($env.Name)" -ForegroundColor Green
            Write-Host "Directory set to: $GAMPath"
            Write-Host "GAM commands can now be run directly using 'gam'."
            Write-Host "Type 'switch <name>' to jump to another environment or 'switch' to return to the menu." -ForegroundColor Cyan

            Set-SwitchFunctions

            $script:LauncherCompleted = $true
            break
        }

        default {
            Write-Host "Invalid option."
        }
    }

    Stop-Transcript

    if ($script:ExitRequested -and -not $script:LauncherCompleted) { break }

    if ($script:LauncherCompleted -and -not $Host.Runspace.IsNested) {
        Write-Host ""
        Write-Host "Launcher complete. You can now run GAM commands in this window." -ForegroundColor Cyan
        Write-Host "Type 'switch' to return to the menu or 'switch <name>' to jump directly." -ForegroundColor Cyan
        Write-Host "Type 'exit' to close when finished." -ForegroundColor Cyan
        $Host.EnterNestedPrompt()

        if (-not $script:SwitchRequested) {
            $script:SwitchRequested = $true
        }
    }

    if ($script:SwitchRequested -and $script:SwitchTarget) {
        $script:PendingTarget = $script:SwitchTarget
    }

    if ($script:LauncherCompleted -and -not $script:ExitRequested) {
        Start-LauncherTranscript
        continue
    }

    break
}

Write-Host "Exiting Universal GAM Launcher v4.6"
