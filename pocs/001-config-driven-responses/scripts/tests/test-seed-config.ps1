#Requires -Version 5.1
<#
Offline, dependency-free seed tests. Run this script, NOT seed-config.ps1, to
test without Azure. The local az function intercepts every CLI call; it never
falls through to an installed CLI. Function mocks do not validate native az.cmd
argument quoting or actual server/CLI concurrency behavior.
#>
$ErrorActionPreference = 'Stop'
$seedPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'seed-config.ps1'

function Assert-SeedTest {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Seed test failed: $Message" }
}

function Reset-SeedMock {
    # Mutate parent shared state; $script: inside a cross-script mock can bind
    # to the invoked seed script instead of this test on Windows PowerShell 5.1.
    $seedMock.Clear()
    $seedMock.Calls = New-Object System.Collections.ArrayList
    $seedMock.Writes = New-Object System.Collections.ArrayList
    $seedMock.ReadCounts = @{}
    $seedMock.Existing = $false
    $seedMock.Conditional = $false
    $seedMock.Mode = ''
    $seedMock.FailOperation = ''
}

function Get-MockArgument {
    param([string[]]$Arguments, [string]$Name)
    $position = [Array]::IndexOf($Arguments, $Name)
    if ($position -lt 0) { return $null }
    return $Arguments[$position + 1]
}

function az {
    $arguments = [string[]]$args
    [void]$seedMock.Calls.Add($arguments)
    $global:LASTEXITCODE = 0
    if ($arguments.Count -lt 3 -or $arguments[0] -ne 'appconfig' -or $arguments[1] -ne 'kv') {
        $global:LASTEXITCODE = 99
        throw 'Unexpected CLI command: offline mock refused it.'
    }
    $operation = $arguments[2]
    if ($arguments -contains '--help') { $operation = 'help' }
    if ($seedMock.FailOperation -eq $operation) {
        $global:LASTEXITCODE = 17
        Write-Output 'PRIVATE_CLI_ERROR_MUST_NOT_LEAK'
        return
    }
    if ($operation -eq 'help') {
        if ($seedMock.Conditional) { return '--if-match ETAG --if-none-match ETAG' }
        return '--key --value --name --label --auth-mode --yes'
    }
    $key = Get-MockArgument $arguments '--key'
    $label = Get-MockArgument $arguments '--label'
    $store = Get-MockArgument $arguments '--name'
    if ($operation -eq 'list') {
        $id = "$store|$label|$key"
        if (-not $seedMock.ReadCounts.ContainsKey($id)) { $seedMock.ReadCounts[$id] = 0 }
        $seedMock.ReadCounts[$id]++
        if ($seedMock.Mode -eq 'malformed') { return 'not-json PRIVATE_CLI_ERROR_MUST_NOT_LEAK' }
        if ($seedMock.Mode -eq 'launch-after-success' -and $seedMock.ReadCounts[$id] -gt 1) {
            # Simulate a command that cannot launch and never updates the sentinel.
            $global:LASTEXITCODE = -1
            throw 'PRIVATE_CLI_ERROR_MUST_NOT_LEAK'
        }
        $exists = $seedMock.Existing
        if ($seedMock.Mode -eq 'appeared' -and $seedMock.ReadCounts[$id] -gt 1) { $exists = $true }
        if (-not $exists) { return '[]' }
        $etag = 'etag-original'
        if ($seedMock.Mode -eq 'changed' -and $seedMock.ReadCounts[$id] -gt 1) { $etag = 'etag-new' }
        if ($seedMock.Mode -eq 'missing-etag') { $etag = '' }
        if ($seedMock.Mode -eq 'wrong-label') { $label = 'unexpected' }
        $record = @{ key = $key; label = $label; etag = $etag; locked = ($seedMock.Mode -eq 'locked') }
        return (ConvertTo-Json -InputObject @($record) -Compress)
    }
    if ($operation -eq 'set') {
        if ($seedMock.Mode -eq 'partial-failure' -and $seedMock.Writes.Count -eq 1) {
            $global:LASTEXITCODE = 17
            return 'PRIVATE_CLI_ERROR_MUST_NOT_LEAK'
        }
        [void]$seedMock.Writes.Add($arguments)
        return
    }
    $global:LASTEXITCODE = 99
    throw 'Unexpected CLI command: offline mock refused it.'
}

function Assert-SeedFailure {
    param([scriptblock]$Action, [string]$Expected)
    $caught = $null
    try { & $Action | Out-Null }
    catch { $caught = $_.Exception.Message }
    Assert-SeedTest ($null -ne $caught) 'expected a terminating failure'
    Assert-SeedTest ($caught -like "*$Expected*") "failure should explain $Expected"
    Assert-SeedTest (-not $caught.Contains('PRIVATE_CLI_ERROR_MUST_NOT_LEAK')) 'CLI error body was leaked'
    Assert-SeedTest ($seedMock.Writes.Count -eq 0) 'failure should not write'
}

$seedMock = @{}
$priorExit = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$hadPriorExit = $null -ne $priorExit
$savedPriorExit = if ($hadPriorExit) { $priorExit.Value } else { $null }
try {
    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($seedPath, [ref]$tokens, [ref]$parseErrors)
    Assert-SeedTest ($parseErrors.Count -eq 0) 'seed script should parse'

    Reset-SeedMock
    & $seedPath -AppConfigName live-test -DraftAppConfigName draft-test -WhatIf
    Assert-SeedTest ($seedMock.Writes.Count -eq 0) 'WhatIf must never mutate'
    Assert-SeedTest ($seedMock.ReadCounts.Count -eq 36) 'WhatIf should preview all 36 scoped settings'

    Reset-SeedMock
    $global:LASTEXITCODE = 73
    & $seedPath -AppConfigName live-test -DraftAppConfigName draft-test -Confirm:$false
    Assert-SeedTest ($seedMock.Writes.Count -eq 36) 'bootstrap should add all three profiles'
    Assert-SeedTest ($global:LASTEXITCODE -eq 73) 'restore prior native exit status after success'
    $filterWrites = @($seedMock.Writes | Where-Object { (Get-MockArgument $_ '--key') -eq 'knowledge:filter' })
    Assert-SeedTest ($filterWrites.Count -eq 3) 'each scope gets an approved healthcare filter'
    foreach ($arguments in $filterWrites) {
        Assert-SeedTest ((Get-MockArgument $arguments '--value') -ceq "industry eq 'healthcare' and status eq 'approved'") 'draft must be approved-only too'
    }
    foreach ($arguments in $seedMock.Writes) {
        Assert-SeedTest ((Get-MockArgument $arguments '--auth-mode') -eq 'login') 'login remains the default auth mode'
        Assert-SeedTest ((Get-MockArgument $arguments '--output') -eq 'none') 'never print written values'
        Assert-SeedTest ($arguments -notcontains '--if-match') 'current CLI fallback must omit unsupported flags'
        if ((Get-MockArgument $arguments '--key') -eq 'experience:persona') {
            Assert-SeedTest ((Get-MockArgument $arguments '--value') -like '*Contoso Health Plan*') 'healthcare persona'
        }
        if ((Get-MockArgument $arguments '--key') -eq 'experience:prompt_asset') {
            $expectedAsset = if ((Get-MockArgument $arguments '--label') -eq 'baseline') { 'response:v1' } else { 'response:v2' }
            Assert-SeedTest ((Get-MockArgument $arguments '--value') -eq $expectedAsset) 'keep style variants'
        }
    }
    foreach ($arguments in $seedMock.Calls) {
        if ($arguments[2] -eq 'list') {
            Assert-SeedTest ($arguments -contains '--fields') 'scoped metadata read'
            Assert-SeedTest ($arguments -notcontains 'value') 'do not export/read values'
            Assert-SeedTest ($arguments -notcontains '--resolve-keyvault') 'never resolve secrets'
        }
    }

    Reset-SeedMock
    $seedMock.Existing = $true
    & $seedPath -AppConfigName live-test -DraftAppConfigName draft-test -Confirm:$false
    Assert-SeedTest ($seedMock.Writes.Count -eq 0) 'default preserves every existing value'

    Reset-SeedMock
    $seedMock.Existing = $true
    & $seedPath -AppConfigName live-test -Keys knowledge:index -OverwriteExisting -Confirm:$false
    Assert-SeedTest ($seedMock.Writes.Count -eq 0) 'overwrite alone must preserve existing customer index'

    Reset-SeedMock
    $seedMock.Existing = $true
    & $seedPath -AppConfigName live-test -Keys knowledge:index -KnowledgeIndex selected-index -Confirm:$false
    Assert-SeedTest ($seedMock.Writes.Count -eq 0) 'index argument alone cannot overwrite'

    Reset-SeedMock
    $seedMock.Existing = $true
    $seedMock.Conditional = $true
    & $seedPath -AppConfigName live-test -DraftAppConfigName draft-test -Keys knowledge:index -Labels candidate -KnowledgeIndex selected-index -OverwriteExisting -Confirm:$false
    Assert-SeedTest ($seedMock.Writes.Count -eq 2) 'explicit index replacement is scoped to candidate in both stores'
    foreach ($arguments in $seedMock.Writes) {
        Assert-SeedTest ((Get-MockArgument $arguments '--value') -eq 'selected-index') 'selected index value'
        Assert-SeedTest ((Get-MockArgument $arguments '--if-match') -eq 'etag-original') 'use ETag when CLI supports it'
    }

    Reset-SeedMock
    $seedMock.Conditional = $true
    & $seedPath -AppConfigName live-test -Keys experience:persona -Labels baseline -AuthMode key -Confirm:$false
    Assert-SeedTest ($seedMock.Writes.Count -eq 1) 'exact key and label scoping'
    Assert-SeedTest ((Get-MockArgument $seedMock.Writes[0] '--if-none-match') -eq '*') 'create-only condition when supported'
    Assert-SeedTest ((Get-MockArgument $seedMock.Writes[0] '--auth-mode') -eq 'key') 'preserve explicit legacy key auth'

    Reset-SeedMock
    & $seedPath -AppConfigName live-test -DraftAppConfigName draft-test -SkipKnowledge -Keys knowledge:filter -Confirm:$false
    Assert-SeedTest ($seedMock.Calls.Count -eq 0) 'SkipKnowledge wins over key selection'

    Reset-SeedMock
    $seedMock.Existing = $true
    & $seedPath -AppConfigName live-test -Keys experience:persona -OverwriteExisting -WhatIf
    Assert-SeedTest ($seedMock.Writes.Count -eq 0) 'WhatIf wins over overwrite'

    foreach ($operation in @('list', 'help', 'set')) {
        Reset-SeedMock
        $seedMock.FailOperation = $operation
        $global:LASTEXITCODE = 73
        Assert-SeedFailure { & $seedPath -AppConfigName live-test -Keys experience:persona -Labels baseline -Confirm:$false } 'Azure CLI operation failed'
        Assert-SeedTest ($global:LASTEXITCODE -eq 73) 'restore prior native exit status after failure'
    }
    foreach ($mode in @('malformed', 'missing-etag', 'wrong-label', 'locked', 'changed', 'appeared', 'launch-after-success')) {
        Reset-SeedMock
        $seedMock.Mode = $mode
        $seedMock.Existing = $mode -in @('missing-etag', 'wrong-label', 'locked', 'changed')
        Assert-SeedFailure { & $seedPath -AppConfigName live-test -Keys experience:persona -Labels baseline -OverwriteExisting -Confirm:$false } ''
    }

    Reset-SeedMock
    $seedMock.Mode = 'partial-failure'
    $caught = $null
    try { & $seedPath -AppConfigName live-test -Labels baseline -Confirm:$false }
    catch { $caught = $_.Exception.Message }
    Assert-SeedTest ($null -ne $caught) 'a partial write failure terminates the run'
    Assert-SeedTest ($seedMock.Writes.Count -eq 1) 'earlier successful keys remain after partial failure'
    $setCalls = @($seedMock.Calls | Where-Object { $_[2] -eq 'set' -and $_ -notcontains '--help' })
    Assert-SeedTest ($setCalls.Count -eq 2) 'do not continue after the failed key'

    Reset-SeedMock
    Assert-SeedFailure { & $seedPath -AppConfigName live-test -Keys 'experience:*' -WhatIf } ''
    Assert-SeedTest ($seedMock.Calls.Count -eq 0) 'invalid scopes fail before CLI calls'
    foreach ($name in @('Uppercase-index', 'index--name', 'index__name')) {
        Reset-SeedMock
        Assert-SeedFailure { & $seedPath -AppConfigName live-test -KnowledgeIndex $name -WhatIf } 'KnowledgeIndex'
        Assert-SeedTest ($seedMock.Calls.Count -eq 0) 'invalid index names fail before CLI calls'
    }
    Write-Host 'PASS: offline seed configuration tests (function-mocked CLI).'
}
finally {
    if ($hadPriorExit) { $global:LASTEXITCODE = $savedPriorExit }
    else { Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
}