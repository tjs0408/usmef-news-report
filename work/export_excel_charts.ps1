param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$ChartSpecsPath
)

$ErrorActionPreference = 'Stop'
$excel = $null
$workbook = $null

try {
    if (-not (Test-Path -LiteralPath $WorkbookPath)) {
        throw "Excel 원본 파일을 찾지 못했습니다."
    }
    if (-not (Test-Path -LiteralPath $ChartSpecsPath)) {
        throw "그래프 내보내기 설정 파일을 찾지 못했습니다."
    }

    $chartSpecs = @(Get-Content -LiteralPath $ChartSpecsPath -Raw | ConvertFrom-Json)
    # Windows PowerShell 5.1은 -File 실행 시 JSON 최상위 배열을 다시 배열 하나로
    # 감싸는 경우가 있다. 이때 명시적으로 한 단계만 평탄화해야 각 사양을 순회한다.
    if ($chartSpecs.Count -eq 1 -and $chartSpecs[0] -is [System.Array]) {
        $chartSpecs = [object[]]$chartSpecs[0]
    }
    if ($chartSpecs.Count -eq 0) {
        throw "내보낼 Excel 그래프 설정이 없습니다."
    }
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

    # Excel 실행·통합문서 열기는 가장 시간이 많이 드는 부분이다. 차트별로
    # 반복하지 않고 하나의 읽기 전용 Excel 세션에서 모두 내보낸다.
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AutomationSecurity = 3
    $workbook = $excel.Workbooks.Open($WorkbookPath, 0, $true)

    foreach ($chartSpec in $chartSpecs) {
        # PSObject 속성을 명시적으로 읽는다. Windows PowerShell은 컬렉션의
        # 속성 열거를 자동 적용할 수 있어, 일반 점 표기만 쓰면 JSON 배열 전체가
        # Int32 변환 대상으로 해석되는 환경이 있다.
        $sheetIndex = [Convert]::ToInt32($chartSpec.PSObject.Properties['sheetIndex'].Value)
        $anchorColumn = [Convert]::ToInt32($chartSpec.PSObject.Properties['anchorColumn'].Value)
        $outputName = [string]$chartSpec.PSObject.Properties['outputName'].Value
        if ([string]::IsNullOrWhiteSpace($outputName) -or
            $outputName.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
            throw "유효하지 않은 그래프 출력 파일명입니다."
        }

        $sheet = $workbook.Worksheets.Item($sheetIndex)

        # 업로드·복제 과정에서 Chart 이름은 바뀔 수 있으므로, 양식에서 약속한
        # 시작 열을 기준으로 대상 차트를 식별한다.
        $targetChart = $null
        for ($index = 1; $index -le $sheet.ChartObjects().Count; $index++) {
            $candidate = $sheet.ChartObjects().Item($index)
            if ([int]$candidate.TopLeftCell.Column -eq $anchorColumn) {
                $targetChart = $candidate
                break
            }
        }
        if ($null -eq $targetChart) {
            throw "지정 위치의 Excel 차트를 찾지 못했습니다. sheet=$sheetIndex, column=$anchorColumn"
        }

        # 일부 차트는 활성화하지 않으면 Export가 성공으로 반환되면서도 0바이트
        # PNG를 만들 수 있다. 화면을 표시하지 않은 상태에서 해당 차트만 렌더링한다.
        $sheet.Activate()
        $targetChart.Activate()
        Start-Sleep -Milliseconds 250
        $outputPath = Join-Path -Path $OutputDirectory -ChildPath $outputName
        if (-not $targetChart.Chart.Export($outputPath)) {
            throw "Excel 차트를 PNG로 내보내지 못했습니다. sheet=$sheetIndex, column=$anchorColumn"
        }
        if (-not (Test-Path -LiteralPath $outputPath) -or (Get-Item -LiteralPath $outputPath).Length -eq 0) {
            throw "Excel 차트 PNG 파일이 만들어지지 않았습니다. sheet=$sheetIndex, column=$anchorColumn"
        }
    }
}
catch {
    $line = $_.InvocationInfo.ScriptLineNumber
    throw "Excel 그래프 일괄 내보내기 실패 (line $line): $($_.Exception.Message)"
}
finally {
    if ($null -ne $workbook) { $workbook.Close($false) }
    if ($null -ne $excel) {
        $excel.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
}
