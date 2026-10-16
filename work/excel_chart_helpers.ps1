function Export-ReportWorkbookCharts {
    param([object]$Workbook, [string]$OutputDirectory, [string]$ChartSpecsPath)
    $chartSpecs = @(Get-Content -LiteralPath $ChartSpecsPath -Raw | ConvertFrom-Json)
    if ($chartSpecs.Count -eq 1 -and $chartSpecs[0] -is [System.Array]) {
        $chartSpecs = [object[]]$chartSpecs[0]
    }
    if ($chartSpecs.Count -eq 0) { throw 'No chart export specifications.' }
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    foreach ($chartSpec in $chartSpecs) {
        $sheetIndex = [Convert]::ToInt32($chartSpec.PSObject.Properties['sheetIndex'].Value)
        $anchorColumn = [Convert]::ToInt32($chartSpec.PSObject.Properties['anchorColumn'].Value)
        $outputName = [string]$chartSpec.PSObject.Properties['outputName'].Value
        if ([string]::IsNullOrWhiteSpace($outputName) -or
            $outputName.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
            throw 'Invalid chart output filename.'
        }
        $sheet = $Workbook.Worksheets.Item($sheetIndex)
        $chartObjects = $sheet.ChartObjects()
        $targetChart = $null
        for ($index = 1; $index -le $chartObjects.Count; $index++) {
            $candidate = $chartObjects.Item($index)
            if ([int]$candidate.TopLeftCell.Column -eq $anchorColumn) {
                $targetChart = $candidate
                break
            }
        }
        if ($null -eq $targetChart) {
            throw "Chart not found. sheet=$sheetIndex, column=$anchorColumn"
        }
        $sheet.Activate()
        $targetChart.Activate()
        Start-Sleep -Milliseconds 250
        $outputPath = Join-Path -Path $OutputDirectory -ChildPath $outputName
        if (-not $targetChart.Chart.Export($outputPath)) {
            throw "Chart PNG export failed. sheet=$sheetIndex, column=$anchorColumn"
        }
        if (-not (Test-Path -LiteralPath $outputPath) -or (Get-Item -LiteralPath $outputPath).Length -eq 0) {
            throw "Chart PNG is empty. sheet=$sheetIndex, column=$anchorColumn"
        }
    }
}
