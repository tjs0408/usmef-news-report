param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][int]$SheetIndex,
    [Parameter(Mandatory = $true)][int]$AnchorColumn
)

$ErrorActionPreference = 'Stop'
$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AutomationSecurity = 3
    $workbook = $excel.Workbooks.Open($WorkbookPath, 0, $true)
    $sheet = $workbook.Worksheets.Item($SheetIndex)

    # 업로드·복제 과정에서 Chart 이름은 바뀔 수 있으므로, 양식에서 약속한
    # 시작 열을 기준으로 대상 차트를 식별한다.
    $targetChart = $null
    for ($index = 1; $index -le $sheet.ChartObjects().Count; $index++) {
        $candidate = $sheet.ChartObjects().Item($index)
        if ([int]$candidate.TopLeftCell.Column -eq $AnchorColumn) {
            $targetChart = $candidate
            break
        }
    }
    if ($null -eq $targetChart) {
        throw "지정 위치의 Excel 차트를 찾지 못했습니다. sheet=$SheetIndex, column=$AnchorColumn"
    }

    # 일부 차트는 활성화하지 않으면 Export가 성공으로 반환되면서도 0바이트
    # PNG를 만들 수 있다. 화면을 표시하지 않은 상태에서 해당 차트만 렌더링한다.
    $sheet.Activate()
    $targetChart.Activate()
    Start-Sleep -Milliseconds 250
    # 확장자를 보고 Excel이 PNG 필터를 선택하게 한다. 일부 설치본은 필터명을
    # 직접 넘기면 차트 형식 오류를 반환한다.
    if (-not $targetChart.Chart.Export($OutputPath)) {
        throw "Excel 차트를 PNG로 내보내지 못했습니다."
    }
    if (-not (Test-Path -LiteralPath $OutputPath) -or (Get-Item -LiteralPath $OutputPath).Length -eq 0) {
        throw "Excel 차트 PNG 파일이 만들어지지 않았습니다."
    }
}
finally {
    if ($null -ne $workbook) { $workbook.Close($false) }
    if ($null -ne $excel) {
        $excel.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
}
