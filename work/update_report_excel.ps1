param(
    [Parameter(Mandatory = $true)][string]$TemplatePath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$PendingPath,
    [Parameter(Mandatory = $true)][string]$MarketDataPath
)

$ErrorActionPreference = 'Stop'
$pending = Get-Content -LiteralPath $PendingPath -Raw | ConvertFrom-Json
$sourceData = Get-Content -LiteralPath $MarketDataPath -Raw | ConvertFrom-Json
$excel = $null
$workbook = $null
$originalCalculation = $null
$originalEnableEvents = $null
$originalScreenUpdating = $null
$calculationOptimizationEnabled = $false

function ConvertTo-ExcelColumnName {
    param([int]$ColumnNumber)

    $columnName = ''
    while ($ColumnNumber -gt 0) {
        $remainder = ($ColumnNumber - 1) % 26
        $columnName = ([char](65 + $remainder)) + $columnName
        $ColumnNumber = [math]::Floor(($ColumnNumber - 1) / 26)
    }
    return $columnName
}

function Set-DisplayedValueComparisonFormulas {
    param(
        [object]$Sheet,
        [int]$ReportDateRow,
        [object[]]$Metrics
    )

    # 보고서 표는 8열이 한 주차 블록이다. 현재·전주·전년 값이 표에 보이는
    # 자릿수와 일치하도록 먼저 반올림한 뒤 증감률을 계산한다.
    # report_육계계란 시트는 서식이 XFD 열까지 남아 있어 UsedRange 기준으로
    # 찾으면 2,048개 주차 블록을 COM으로 매번 순회한다. 보고일자 행의 실제
    # 마지막 헤더만 기준으로 삼으면 현재·과거 유효 주차만 갱신할 수 있다.
    $xlToLeft = -4159
    $lastColumn = $Sheet.Cells.Item($ReportDateRow, $Sheet.Columns.Count).End($xlToLeft).Column
    for ($blockStartColumn = 1; $blockStartColumn -le $lastColumn; $blockStartColumn += 8) {
        $reportDateText = [string]$Sheet.Cells.Item($ReportDateRow, $blockStartColumn).Value2
        if (-not [regex]::IsMatch($reportDateText, '\d{4}-\d{1,2}-\d{1,2}')) { continue }

        foreach ($metric in $Metrics) {
            $row = [int]$metric.row
            $digits = [int]$metric.digits
            $currentRef = "$(ConvertTo-ExcelColumnName ($blockStartColumn + 4))$row"
            $previousWeekRef = "$(ConvertTo-ExcelColumnName ($blockStartColumn + 3))$row"
            $previousYearRef = "$(ConvertTo-ExcelColumnName ($blockStartColumn + 2))$row"
            $weekComparisonRef = "$(ConvertTo-ExcelColumnName ($blockStartColumn + 5))$row"
            $yearComparisonRef = "$(ConvertTo-ExcelColumnName ($blockStartColumn + 6))$row"

            $blank = '""'
            $weekFormula = "=IFERROR(IF(OR($currentRef=$blank,$previousWeekRef=$blank),$blank,(ROUND($currentRef,$digits)-ROUND($previousWeekRef,$digits))/ROUND($previousWeekRef,$digits)),$blank)"
            $yearFormula = "=IFERROR(IF(OR($currentRef=$blank,$previousYearRef=$blank),$blank,(ROUND($currentRef,$digits)-ROUND($previousYearRef,$digits))/ROUND($previousYearRef,$digits)),$blank)"
            try {
                $Sheet.Range($weekComparisonRef).Formula = $weekFormula
                $Sheet.Range($yearComparisonRef).Formula = $yearFormula
            }
            catch {
                throw "Unable to assign rounded comparison formula. sheet=$($Sheet.Name), reportDate=$reportDateText, row=$row, weekCell=$weekComparisonRef, yearCell=$yearComparisonRef, error=$($_.Exception.Message)"
            }
        }
    }
}

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    # 외부 연결은 이 보고서가 사용하지 않으므로 열 때 갱신하지 않는다.
    $workbook = $excel.Workbooks.Open($TemplatePath, 0, $false)
    # 수백 개의 셀·수식 변경 중 자동 재계산을 막고, 마지막 CalculateFull 한 번에
    # 계산한다. 일부 Office 환경은 통합문서가 열리기 전 Calculation 변경을
    # 허용하지 않으므로, 열기 뒤에만 적용하고 실패 시 기존 방식으로 계속한다.
    $originalCalculation = $excel.Calculation
    $originalEnableEvents = $excel.EnableEvents
    $originalScreenUpdating = $excel.ScreenUpdating
    $excel.EnableEvents = $false
    $excel.ScreenUpdating = $false
    try {
        $excel.Calculation = -4135 # xlCalculationManual
        $calculationOptimizationEnabled = $true
    }
    catch {
        Write-Warning "Excel 수동 계산 모드를 설정하지 못해 기존 자동 계산 방식으로 계속합니다."
    }

    foreach ($item in $pending) {
        $sheet = $workbook.Worksheets.Item([string]$item.sheetName)
        $row = [int]$item.row

        if ($item.market -eq 'eu_pork_germany') {
            $germanyData = $sourceData.euGermanyPrices | Where-Object { $_.weekEnded -eq $item.weekEnded } | Select-Object -First 1
            if ($null -eq $germanyData) { continue }
            # 독일 지육가격(€/100kg)은 AHDB 원자료를 소수 둘째 자리까지 그대로 입력한다.
            $sheet.Range("$($item.currentColumn)$row").Value2 = [math]::Round([double]$germanyData.germanyPrice, 2)
            $sheet.Range("$($item.kgPriceColumn)$row").Formula = "=ROUND($($item.currentColumn)$row/100,2)"
            $sheet.Range("$($item.exchangeColumn)$row").Value2 = [double]$item.euroExchangeRate
            # 원화 지육가격(원/100kg)은 정수 단위로 반올림한다.
            $sheet.Range("$($item.wonPriceColumn)$row").Formula = "=ROUND($($item.currentColumn)$row*$($item.exchangeColumn)$row,0)"
            $sheet.Range("$($item.wonKgPriceColumn)$row").Formula = "=$($item.wonPriceColumn)$row/100"
            # 빈 신규 행도 바로 위 기존 행의 숫자 표시 형식을 그대로 사용한다.
            $sheet.Range("$($item.wonPriceColumn)$row").NumberFormat = $sheet.Range("$($item.wonPriceColumn)$($row - 1)").NumberFormat
            $sheet.Range("$($item.wonKgPriceColumn)$row").NumberFormat = $sheet.Range("$($item.wonKgPriceColumn)$($row - 1)").NumberFormat
            continue
        }

        if ($item.market -eq 'japan_egg') {
            $eggData = $sourceData.japanEggPrices | Where-Object { $_.priceDate -eq $item.priceDate } | Select-Object -First 1
            if ($null -eq $eggData) { continue }
            # JA 전농타마고 도쿄 M란 기준치(엔/kg)와 네이버 증권의 100엔 기준 환율을 입력한다.
            # AA 열의 기존 '=Y*Z/100' 계산식은 그대로 두어 원화 가격도 함께 갱신된다.
            $sheet.Range("$($item.currentColumn)$row").Value2 = [double]$eggData.tokyoMPrice
            $sheet.Range("$($item.exchangeColumn)$row").Value2 = [double]$item.jpyExchangeRate
            continue
        }

        if ($item.market -eq 'us_egg') {
            $eggData = $sourceData.usEggData | Where-Object { $_.weekEnded -eq $item.weekEnded } | Select-Object -First 1
            if ($null -eq $eggData) { continue }
            # Slug 1427의 6-Area Total(30-dozen cases, thousand)과 Slug 2848의
            # National Shell Eggs - Caged Large Average Price(cents/dozen)를 입력한다.
            # AA·AC·AE 열의 기존 계산식은 보존하여 단위 환산·원화 가격도 함께 갱신한다.
            $sheet.Range("$($item.inventoryColumn)$row").Value2 = [double]$eggData.weeklyInventory
            $sheet.Range("$($item.priceColumn)$row").Value2 = [double]$eggData.largeAveragePrice
            $sheet.Range("$($item.exchangeColumn)$row").Value2 = [double]$item.usdExchangeRate
            continue
        }

        if ($item.market -eq 'brazil_chicken') {
            $chickenData = $sourceData.brazilChickenPrices | Where-Object { $_.weekEnded -eq $item.weekEnded } | Select-Object -First 1
            if ($null -eq $chickenData) { continue }
            # CEPEA 동결 닭고기 가격 시리즈의 À vista R$/kg와 BRL/KRW 환율을 입력한다.
            # 양식의 기존 계산식과 같은 R열×S열을 T열에 적용해 원/kg 가격을 유지한다.
            $sheet.Range("$($item.currentColumn)$row").Value2 = [math]::Round([double]$chickenData.cashPrice, 2)
            $sheet.Range("$($item.exchangeColumn)$row").Value2 = [double]$item.brlExchangeRate
            $sheet.Range("$($item.wonPriceColumn)$row").Formula = "=$($item.currentColumn)$row*$($item.exchangeColumn)$row"
            $sheet.Range("$($item.wonPriceColumn)$row").NumberFormat = $sheet.Range("$($item.wonPriceColumn)$($row - 1)").NumberFormat
            continue
        }

        if ($item.market -eq 'us_chicken') {
            $chickenData = $sourceData.usChickenPrices | Where-Object { $_.weekEnded -eq $item.weekEnded } | Select-Object -First 1
            if ($null -eq $chickenData) { continue }
            # Slug 3208의 Chicken (Young) WTD와 Slug 3646 첫 페이지의
            # National Composite WOGS Wtd Avg(cents/lb)를 입력한다.
            # 양식의 기존 천두·단위·원화 환산 계산식은 보존한다.
            $sheet.Range("$($item.slaughterColumn)$row").Value2 = [double]$chickenData.weeklySlaughter
            $sheet.Range("$($item.currentColumn)$row").Value2 = [math]::Round([double]$chickenData.wtdAvg, 2)
            # 미국 육계 그래프는 닭-미국 표의 같은 주차보다 4행 위에 배치되어 있다.
            # Slug 3646의 Wtd Avg를 2026YMD(F) 열에 같이 넣어 그래프를 즉시 갱신한다.
            if ($null -ne $item.graphSheetName -and $null -ne $item.graphColumn -and $null -ne $item.graphRowOffset) {
                $graphSheet = $workbook.Worksheets.Item([string]$item.graphSheetName)
                $graphRow = $row + [int]$item.graphRowOffset
                if ($graphRow -gt 1) {
                    $graphSheet.Range("$($item.graphColumn)$graphRow").Value2 = [math]::Round([double]$chickenData.wtdAvg, 2)
                }
            }
            continue
        }

        if ($item.market -eq 'australia_beef') {
            $australiaData = $sourceData.australiaBeefData | Where-Object { $_.weekEnded -eq $item.weekEnded } | Select-Object -First 1
            if ($null -eq $australiaData) { continue }
            # MLA National Slaughter의 Cattle 합계와 EYCI를 입력하고, 양식의
            # 기존 천두·AUD·원화 환산 구조를 같은 수식으로 유지한다.
            $sheet.Range("$($item.slaughterColumn)$row").Value2 = [double]$australiaData.slaughterCount
            $sheet.Range("$($item.thousandHeadColumn)$row").Formula = "=$($item.slaughterColumn)$row/1000"
            $sheet.Range("$($item.eyciColumn)$row").Value2 = [math]::Round([double]$australiaData.eyci, 2)
            $sheet.Range("$($item.audPriceColumn)$row").Formula = "=$($item.eyciColumn)$row/100"
            $sheet.Range("$($item.exchangeColumn)$row").Value2 = [double]$item.audExchangeRate
            $sheet.Range("$($item.wonPriceColumn)$row").Formula = "=$($item.audPriceColumn)$row*$($item.exchangeColumn)$row"
            continue
        }

        $data = $sourceData.marketData | Where-Object { $_.reportDate -eq $item.reportDate } | Select-Object -First 1
        if ($null -eq $data) { continue }
        $isPork = $item.market -eq 'pork'
        if ($isPork) {
            $slaughterCount = $data.porkSlaughterCount
            $previousSlaughterCount = $data.porkPreviousSlaughterCount
            $cutoutPrice = $data.porkCutoutPrice
        } else {
            $slaughterCount = $data.slaughterCount
            $previousSlaughterCount = $data.previousSlaughterCount
            $cutoutPrice = $data.cutoutPrice
        }

        $sheet.Range("$($item.currentColumn)$row").Value2 = [double]$slaughterCount
        $sheet.Range("$($item.revisionColumn)$row").ClearContents()
        $sheet.Range("$($item.priceColumn)$row").Value2 = [double]$cutoutPrice
        $sheet.Range("$($item.kgPriceColumn)$row").Formula = "=$($item.priceColumn)$row*2.20462"
        $sheet.Range("$($item.exchangeColumn)$row").Value2 = [double]$item.exchangeRate
        $sheet.Range("$($item.wonPriceColumn)$row").Formula = "=$($item.kgPriceColumn)$row*$($item.exchangeColumn)$row"

        $previousRow = $row - 1
        $recordedPrevious = $sheet.Range("$($item.currentColumn)$previousRow").Value2
        if ($null -ne $previousSlaughterCount -and ($null -eq $recordedPrevious -or [double]$previousSlaughterCount -ne [double]$recordedPrevious)) {
            # 다음 주 뉴스의 전 주 도축두수는 USDA가 확정·수정한 이전 주차 값이다.
            # 소·돼지 모두 이전 주차의 실제 도축두수를 수정하고, 기존 입력값은 수정 전 열에 보관한다.
            $sheet.Range("$($item.currentColumn)$previousRow").Value2 = [double]$previousSlaughterCount
            if ($null -ne $recordedPrevious) {
                $sheet.Range("$($item.revisionColumn)$previousRow").Value2 = [double]$recordedPrevious
            }
        }
    }

    # 미국 육계 그래프는 닭-미국 시트의 기존·신규 Wtd Avg를 모두 반영한다.
    # 닭-미국 표 39행은 그래프 35행처럼 동일 주차가 정확히 4행 위에 있으므로,
    # Z열에 이미 값이 있는 경우도 매번 F열로 동기화해 빈 그래프 셀을 보정한다.
    $usChickenSheet = $workbook.Worksheets.Item(7)
    $usChickenGraphSheet = $workbook.Worksheets.Item(8)
    for ($sourceRow = 7; $sourceRow -le $usChickenSheet.UsedRange.Rows.Count; $sourceRow++) {
        $wtdAverage = $usChickenSheet.Range("Z$sourceRow").Value2
        if ($null -eq $wtdAverage -or [string]::IsNullOrWhiteSpace([string]$wtdAverage)) { continue }
        $graphRow = $sourceRow - 4
        if ($graphRow -gt 1) {
            $usChickenGraphSheet.Range("F$graphRow").Value2 = [math]::Round([double]$wtdAverage, 2)
        }
    }

    # 브라질그래프는 날짜 열 없이 월별 거래일 순서로 값이 나열된 양식이다.
    # CEPEA 원본의 전월·당월 À vista R$를 월별 시작 행부터 날짜순으로 다시 맞춘다.
    $graphPrices = @($sourceData.brazilChickenGraphPrices | Sort-Object { [datetime]$_.priceDate })
    if ($graphPrices.Count -gt 0) {
        # 기준 양식에서 브라질그래프는 10번째 시트다. 한글 시트명을 직접 넘기면
        # Windows PowerShell의 코드페이지에 따라 COM이 이름을 읽지 못할 수 있다.
        $graphSheet = $workbook.Worksheets.Item(10)
        $monthlyPrices = $graphPrices | Group-Object { ([datetime]$_.priceDate).ToString('yyyy-MM') }
        foreach ($monthGroup in $monthlyPrices) {
            $firstDate = [datetime]$monthGroup.Group[0].priceDate
            $yearHeader = "$($firstDate.Year)$([char]0xB144)"
            $yearColumn = $null
            for ($column = 4; $column -le $graphSheet.UsedRange.Columns.Count; $column++) {
                if ([string]$graphSheet.Cells.Item(2, $column).Value2 -eq $yearHeader) {
                    $yearColumn = $column
                    break
                }
            }
            # 2026년 기준 양식의 연도 열은 H열이다. 헤더의 코드페이지 차이에도
            # 현재 양식을 안정적으로 갱신할 수 있도록 이 값을 보완값으로 사용한다.
            if ($null -eq $yearColumn -and $firstDate.Year -eq 2026) { $yearColumn = 8 }
            if ($null -eq $yearColumn) { continue }

            $monthLabel = "$($firstDate.Month)$([char]0xC6D4)"
            $monthStartRow = $null
            $nextMonthRow = $graphSheet.UsedRange.Rows.Count + 1
            for ($candidateRow = 3; $candidateRow -le $graphSheet.UsedRange.Rows.Count; $candidateRow++) {
                $label = [string]$graphSheet.Cells.Item($candidateRow, 3).Value2
                if ($null -eq $monthStartRow -and $label -eq $monthLabel) {
                    $monthStartRow = $candidateRow
                    continue
                }
                if ($null -ne $monthStartRow -and $label.Length -gt 1 -and $label.EndsWith([string][char]0xC6D4)) {
                    $nextMonthRow = $candidateRow
                    break
                }
            }
            # 현재 2026 양식의 월별 시작 행. 한글 레이블의 코드페이지 차이를 보완한다.
            $monthStartRows2026 = @{ 1 = 3; 2 = 25; 3 = 44; 4 = 64; 5 = 86; 6 = 107; 7 = 127; 8 = 150; 9 = 172 }
            if ($null -eq $monthStartRow -and $firstDate.Year -eq 2026 -and $monthStartRows2026.ContainsKey($firstDate.Month)) {
                $monthStartRow = [int]$monthStartRows2026[$firstDate.Month]
                $nextMonthRow = if ($monthStartRows2026.ContainsKey($firstDate.Month + 1)) {
                    [int]$monthStartRows2026[$firstDate.Month + 1]
                } else {
                    $graphSheet.UsedRange.Rows.Count + 1
                }
            }
            if ($null -ne $monthStartRow) {
                $graphRow = $monthStartRow
                foreach ($graphPrice in $monthGroup.Group) {
                    if ($graphRow -ge $nextMonthRow) { break }
                    $graphSheet.Cells.Item($graphRow, $yearColumn).Value2 = [math]::Round([double]$graphPrice.cashPrice, 2)
                    $graphRow++
                }
            }
        }
    }

    # report 시트는 기존의 연결·계산 수식을 그대로 사용한다. 생성일 기준 가장
    # 최근 목요일을 보고일자로 기록하면, 예를 들어 2026-09-11 실행 시에는
    # '보고일자 : 2026-9-10'이 표시된다.
    $reportDate = [datetime]::Today
    $daysSinceThursday = (([int]$reportDate.DayOfWeek - [int][System.DayOfWeek]::Thursday + 7) % 7)
    $reportDate = $reportDate.AddDays(-$daysSinceThursday)
    $reportSheet = $workbook.Worksheets.Item(1)
    # Windows PowerShell의 ANSI 코드페이지와 무관하게 '보고일자'를 기록한다.
    $reportLabel = ([string][char]0xBCF4) + ([string][char]0xACE0) + ([string][char]0xC77C) + ([string][char]0xC790)

    # report 시트는 8열을 한 주차 단위로 사용한다. 기존 양식의 첫 보고일자
    # (A209)를 기준으로 이번 주차의 시작 열을 계산해, 다음 주차 표도 같은
    # 서식과 산식으로 확장한다. 이전에는 KC209의 보고일자만 기록되어 아래
    # 쇠고기·돼지고기 표가 비어 있었다.
    $firstReportDateText = [string]$reportSheet.Cells.Item(209, 1).Value2
    $firstReportDateMatch = [regex]::Match($firstReportDateText, '(\d{4})-(\d{1,2})-(\d{1,2})')
    if ($firstReportDateMatch.Success) {
        $firstReportDate = [datetime]::new(
            [int]$firstReportDateMatch.Groups[1].Value,
            [int]$firstReportDateMatch.Groups[2].Value,
            [int]$firstReportDateMatch.Groups[3].Value
        )
        $reportWeekOffset = [math]::Floor(($reportDate.Date - $firstReportDate.Date).TotalDays / 7)
        $reportStartColumn = 1 + (8 * [int]$reportWeekOffset)
    } else {
        # 기존 양식의 2026-09-10 위치(KC)를 안전한 예비값으로 사용한다.
        $reportStartColumn = 289
    }

    $reportBlockTopRow = 211
    $reportBlockBottomRow = 236
    $createdReportBlockColumns = @()
    # 기준 파일에 누락된 중간 보고 주차가 있으면, 가장 오래된 주차부터 순서대로
    # 이전 표를 복제한다. 예: 8/27 다음이 비어 있으면 9/3(JU)부터 만들고,
    # 그 블록을 이어 받아 9/10(KC)도 생성한다.
    for ($weeksBack = 3; $weeksBack -ge 0; $weeksBack--) {
        $blockStartColumn = $reportStartColumn - (8 * $weeksBack)
        if ($blockStartColumn -lt 1) { continue }
        $blockReportDate = $reportDate.AddDays(-7 * $weeksBack)
        $reportSheet.Cells.Item(209, $blockStartColumn).Value2 = "$reportLabel : $($blockReportDate.ToString('yyyy-M-d'))"

        $previousBlockStartColumn = $blockStartColumn - 8
        $reportBlockIsBlank = [string]::IsNullOrWhiteSpace([string]$reportSheet.Cells.Item($reportBlockTopRow, $blockStartColumn).Value2)
        if (-not $reportBlockIsBlank -or $previousBlockStartColumn -lt 1) { continue }
        $previousReportBlock = $reportSheet.Range(
            $reportSheet.Cells.Item($reportBlockTopRow, $previousBlockStartColumn),
            $reportSheet.Cells.Item($reportBlockBottomRow, $previousBlockStartColumn + 7)
        )
        $targetReportBlock = $reportSheet.Range(
            $reportSheet.Cells.Item($reportBlockTopRow, $blockStartColumn),
            $reportSheet.Cells.Item($reportBlockBottomRow, $blockStartColumn + 7)
        )
        $previousReportBlock.Copy($targetReportBlock)
        $createdReportBlockColumns += $blockStartColumn
    }

    # 이전 주차 블록에는 당시의 실제 값이 상수로 남아 있다. 새 블록은
    # report 시트의 중간 원본표가 아니라 각 수집 시트의 실제 주차 행을
    # 직접 찾는다. 예를 들어 2026-09-10 보고서는 36주차인 소·돼지 미국
    # 2026-09-04, 소 호주 2026-09-03, 돼지 독일 2026-09-06 값을 사용한다.
    # 이미 생성된 블록도 이 수식을 다시 기록해, 기준 파일을 재업로드해도
    # 예전 연결이 남지 않게 한다.
    # 보고 주차의 실적(KG)뿐 아니라 전주 비교값(KF)도 직접 연결한다.
    # 늦게 공개된 전주 데이터는 다음 생성 때 이 수식으로 자동 반영된다.
    $reportValuePeriods = @(
        @{ targetColumn = $reportStartColumn + 4; weekOffset = 0 }
        @{ targetColumn = $reportStartColumn + 3; weekOffset = -7 }
    )
    # 최신 보고서 블록은 항상 최신 수집값으로 갱신한다. 최근 3개 이전
    # 보고서 블록도 당시 지연 공개로 비어 있던 셀이 있으면 함께 보완한다.
    # 따라서 3주치가 밀린 기준 파일을 다시 생성해도 빈칸이 자동으로 채워진다.
    $reportBlocksForData = @()
    for ($weeksBack = 0; $weeksBack -le 3; $weeksBack++) {
        $blockStartColumn = $reportStartColumn - (8 * $weeksBack)
        if ($blockStartColumn -lt 1) { break }
        $reportBlocksForData += @{
            startColumn = $blockStartColumn
            reportDate = $reportDate.AddDays(-7 * $weeksBack)
            overwrite = (($weeksBack -eq 0) -or ($createdReportBlockColumns -contains $blockStartColumn))
        }
    }
    $reportSourceLinks = @(
        @{ targetRow = 214; sheetIndex = 3; dateColumn = 'EO'; valueColumn = 'EQ'; availabilityColumn = 'EQ'; dateOffset = -6 }
        @{ targetRow = 215; sheetIndex = 3; dateColumn = 'EO'; valueColumn = 'ET'; availabilityColumn = 'EQ'; dateOffset = -6 }
        @{ targetRow = 216; sheetIndex = 3; dateColumn = 'EO'; valueColumn = 'EV'; availabilityColumn = 'EQ'; dateOffset = -6 }
        @{ targetRow = 221; sheetIndex = 4; dateColumn = 'EZ'; valueColumn = 'FC'; availabilityColumn = 'FB'; dateOffset = -7 }
        @{ targetRow = 222; sheetIndex = 4; dateColumn = 'EZ'; valueColumn = 'FE'; availabilityColumn = 'FB'; dateOffset = -7 }
        @{ targetRow = 223; sheetIndex = 4; dateColumn = 'EZ'; valueColumn = 'FG'; availabilityColumn = 'FB'; dateOffset = -7 }
        @{ targetRow = 228; sheetIndex = 5; dateColumn = 'FD'; valueColumn = 'FF'; availabilityColumn = 'FF'; dateOffset = -6 }
        @{ targetRow = 229; sheetIndex = 5; dateColumn = 'FD'; valueColumn = 'FI'; availabilityColumn = 'FF'; dateOffset = -6 }
        @{ targetRow = 230; sheetIndex = 5; dateColumn = 'FD'; valueColumn = 'FK'; availabilityColumn = 'FF'; dateOffset = -6 }
        @{ targetRow = 235; sheetIndex = 6; dateColumn = 'LH'; valueColumn = 'LK'; availabilityColumn = 'LJ'; dateOffset = -4 }
        @{ targetRow = 236; sheetIndex = 6; dateColumn = 'LH'; valueColumn = 'LN'; availabilityColumn = 'LJ'; dateOffset = -4 }
    )
    foreach ($reportBlock in $reportBlocksForData) {
        foreach ($period in $reportValuePeriods) {
            foreach ($link in $reportSourceLinks) {
                $targetColumn = [int]$reportBlock.startColumn + ([int]$period.targetColumn - $reportStartColumn)
                $targetCell = $reportSheet.Cells.Item([int]$link.targetRow, $targetColumn)
                if (-not $reportBlock.overwrite -and -not [string]::IsNullOrWhiteSpace([string]$targetCell.Value2)) {
                    continue
                }
                $sourceDate = $reportBlock.reportDate.AddDays([int]$link.dateOffset + [int]$period.weekOffset)
            $dateFormula = "DATE($($sourceDate.Year),$($sourceDate.Month),$($sourceDate.Day))"
            $sourceSheetName = $workbook.Worksheets.Item([int]$link.sheetIndex).Name
            $dateRange = "'$sourceSheetName'!`$$($link.dateColumn)`$8:`$$($link.dateColumn)`$59"
            $valueRange = "'$sourceSheetName'!`$$($link.valueColumn)`$8:`$$($link.valueColumn)`$59"
            $availabilityRange = "'$sourceSheetName'!`$$($link.availabilityColumn)`$8:`$$($link.availabilityColumn)`$59"
            $lookup = "MATCH($dateFormula,$dateRange,0)"
            $sourceValue = "INDEX($valueRange,$lookup)"
            $availabilityValue = "INDEX($availabilityRange,$lookup)"
            $blank = '""'
            $reportFormula = "=IFERROR(IF($availabilityValue=$blank,$blank,$sourceValue),$blank)"
            try {
                $targetCell.Formula = $reportFormula
            } catch {
                throw "Unable to assign report source formula. row=$($link.targetRow), formula=$reportFormula, error=$($_.Exception.Message)"
            }
            }
        }
    }

    # report_육계계란 시트도 같은 8열 주차 블록 구조다. 누락된 주차 표를
    # 순서대로 생성하고, 육계 미국·브라질의 현재 주차 값은 수집 시트의
    # 실제 데이터 행을 직접 연결한다.
    $chickenEggReportSheet = $workbook.Worksheets.Item(2)
    $chickenEggFirstDateText = [string]$chickenEggReportSheet.Cells.Item(62, 1).Value2
    $chickenEggFirstDateMatch = [regex]::Match($chickenEggFirstDateText, '(\d{4})-(\d{1,2})-(\d{1,2})')
    if ($chickenEggFirstDateMatch.Success) {
        $chickenEggFirstDate = [datetime]::new(
            [int]$chickenEggFirstDateMatch.Groups[1].Value,
            [int]$chickenEggFirstDateMatch.Groups[2].Value,
            [int]$chickenEggFirstDateMatch.Groups[3].Value
        )
        $chickenEggWeekOffset = [math]::Floor(($reportDate.Date - $chickenEggFirstDate.Date).TotalDays / 7)
        $chickenEggTargetStartColumn = 1 + (8 * [int]$chickenEggWeekOffset)
        $chickenEggTopRow = 64
        $chickenEggBottomRow = 88
        $createdChickenEggBlockColumns = @()

        # 앞쪽부터 복사해야 중간에 비어 있던 여러 주차도 정상적인 표·산식을
        # 이어 받을 수 있다.
        for ($weekIndex = 1; $weekIndex -le $chickenEggWeekOffset; $weekIndex++) {
            $blockStartColumn = 1 + (8 * $weekIndex)
            $blockReportDate = $chickenEggFirstDate.AddDays(7 * $weekIndex)
            $chickenEggReportSheet.Cells.Item(62, $blockStartColumn).Value2 = "$reportLabel : $($blockReportDate.ToString('yyyy-M-d'))"
            $blockIsBlank = [string]::IsNullOrWhiteSpace([string]$chickenEggReportSheet.Cells.Item($chickenEggTopRow, $blockStartColumn).Value2)
            if (-not $blockIsBlank) { continue }
            $previousBlock = $chickenEggReportSheet.Range(
                $chickenEggReportSheet.Cells.Item($chickenEggTopRow, $blockStartColumn - 8),
                $chickenEggReportSheet.Cells.Item($chickenEggBottomRow, $blockStartColumn - 1)
            )
            $targetBlock = $chickenEggReportSheet.Range(
                $chickenEggReportSheet.Cells.Item($chickenEggTopRow, $blockStartColumn),
                $chickenEggReportSheet.Cells.Item($chickenEggBottomRow, $blockStartColumn + 7)
            )
            $previousBlock.Copy($targetBlock)
            $createdChickenEggBlockColumns += $blockStartColumn
        }

        # 수식 복사 후 현재 주차 열은 실제 수집 시트의 동일 금요일 데이터를
        # 연결한다. 현재 주차와 최근 3주, 그리고 새로 만들어진 블록을 갱신한다.
        $chickenEggSourceLinks = @(
            @{ targetRow = 67; sheetIndex = 7; dateColumn = 'V'; valueColumn = 'X'; availabilityColumn = 'X'; divideBy = 1000; dateOffset = -6 }
            @{ targetRow = 68; sheetIndex = 7; dateColumn = 'V'; valueColumn = 'AA'; availabilityColumn = 'X'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 69; sheetIndex = 7; dateColumn = 'V'; valueColumn = 'AC'; availabilityColumn = 'X'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 74; sheetIndex = 9; dateColumn = 'P'; valueColumn = 'R'; availabilityColumn = 'R'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 75; sheetIndex = 9; dateColumn = 'P'; valueColumn = 'T'; availabilityColumn = 'R'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 80; sheetIndex = 11; dateColumn = 'X'; valueColumn = 'AA'; availabilityColumn = 'AA'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 81; sheetIndex = 11; dateColumn = 'X'; valueColumn = 'AC'; availabilityColumn = 'AA'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 82; sheetIndex = 11; dateColumn = 'X'; valueColumn = 'AE'; availabilityColumn = 'AA'; divideBy = 1; dateOffset = -6 }
            @{ targetRow = 87; sheetIndex = 12; dateColumn = 'V'; valueColumn = 'Y'; availabilityColumn = 'Y'; divideBy = 1; dateOffset = -7 }
            @{ targetRow = 88; sheetIndex = 12; dateColumn = 'V'; valueColumn = 'AA'; availabilityColumn = 'Y'; divideBy = 1; dateOffset = -7 }
        )
        for ($weeksBack = 0; $weeksBack -le $chickenEggWeekOffset; $weeksBack++) {
            $blockStartColumn = $chickenEggTargetStartColumn - (8 * $weeksBack)
            $shouldRefresh = ($weeksBack -le 3) -or ($createdChickenEggBlockColumns -contains $blockStartColumn)
            if (-not $shouldRefresh) { continue }
            $blockReportDate = $reportDate.AddDays(-7 * $weeksBack)
            $currentValueColumn = $blockStartColumn + 4
            foreach ($link in $chickenEggSourceLinks) {
                $sourceDate = $blockReportDate.AddDays([int]$link.dateOffset)
                $dateFormula = "DATE($($sourceDate.Year),$($sourceDate.Month),$($sourceDate.Day))"
                $sourceSheetName = $workbook.Worksheets.Item([int]$link.sheetIndex).Name
                $dateRange = "'$sourceSheetName'!`$$($link.dateColumn)`$6:`$$($link.dateColumn)`$57"
                $valueRange = "'$sourceSheetName'!`$$($link.valueColumn)`$6:`$$($link.valueColumn)`$57"
                $availabilityRange = "'$sourceSheetName'!`$$($link.availabilityColumn)`$6:`$$($link.availabilityColumn)`$57"
                $lookup = "MATCH($dateFormula,$dateRange,0)"
                $sourceValue = "INDEX($valueRange,$lookup)"
                if ([int]$link.divideBy -ne 1) {
                    $sourceValue = "($sourceValue/$($link.divideBy))"
                }
                $availabilityValue = "INDEX($availabilityRange,$lookup)"
                $blank = '""'
                $chickenEggFormula = "=IFERROR(IF($availabilityValue=$blank,$blank,$sourceValue),$blank)"
                try {
                    $chickenEggReportSheet.Cells.Item([int]$link.targetRow, $currentValueColumn).Formula = $chickenEggFormula
                } catch {
                    throw "Unable to assign poultry report source formula. row=$($link.targetRow), formula=$chickenEggFormula, error=$($_.Exception.Message)"
                }
            }
        }
    }

    # 2025년 9월 1주부터 비어 있던 report_육계계란의 과거 표도, 각 시트에
    # 보존된 2025년 원본 영역을 직접 참조해 현행화한다.
    $historicPoultryLinks = @(
        # 2025년 표의 목요일 보고일자는 다음 날 금요일의 같은 주차 원본을 쓴다.
        @{ targetRow = 38; sheetIndex = 7; dateColumn = 'M'; valueColumn = 'P'; availabilityColumn = 'O'; dateOffset = 1 }
        @{ targetRow = 39; sheetIndex = 7; dateColumn = 'M'; valueColumn = 'R'; availabilityColumn = 'R'; dateOffset = 1 }
        @{ targetRow = 40; sheetIndex = 7; dateColumn = 'M'; valueColumn = 'T'; availabilityColumn = 'R'; dateOffset = 1 }
        @{ targetRow = 45; sheetIndex = 9; dateColumn = 'J'; valueColumn = 'L'; availabilityColumn = 'L'; dateOffset = 1 }
        @{ targetRow = 46; sheetIndex = 9; dateColumn = 'J'; valueColumn = 'N'; availabilityColumn = 'L'; dateOffset = 1 }
        @{ targetRow = 51; sheetIndex = 11; dateColumn = 'O'; valueColumn = 'R'; availabilityColumn = 'R'; dateOffset = 1 }
        @{ targetRow = 52; sheetIndex = 11; dateColumn = 'O'; valueColumn = 'T'; availabilityColumn = 'R'; dateOffset = 1 }
        @{ targetRow = 53; sheetIndex = 11; dateColumn = 'O'; valueColumn = 'V'; availabilityColumn = 'R'; dateOffset = 1 }
        # 2025년 일본 원본은 금요일 기준이다. 보고일자 9/4의 9월 1주는
        # 다음 날 9/5에 해당하는 36주차를 사용한다.
        @{ targetRow = 58; sheetIndex = 12; dateColumn = 'O'; valueColumn = 'R'; availabilityColumn = 'R'; dateOffset = 1 }
        @{ targetRow = 59; sheetIndex = 12; dateColumn = 'O'; valueColumn = 'T'; availabilityColumn = 'R'; dateOffset = 1 }
    )
    $historicStartDate = [datetime]'2025-09-04'
    $historicEndDate = [datetime]'2026-01-01'
    for ($historicWeekIndex = 0; $historicWeekIndex -le 52; $historicWeekIndex++) {
        $historicBlockStartColumn = 1 + (8 * $historicWeekIndex)
        $historicReportText = [string]$chickenEggReportSheet.Cells.Item(33, $historicBlockStartColumn).Value2
        $historicReportMatch = [regex]::Match($historicReportText, '(\d{4})-(\d{1,2})-(\d{1,2})')
        if (-not $historicReportMatch.Success) { continue }
        $historicReportDate = [datetime]::new(
            [int]$historicReportMatch.Groups[1].Value,
            [int]$historicReportMatch.Groups[2].Value,
            [int]$historicReportMatch.Groups[3].Value
        )
        if ($historicReportDate -lt $historicStartDate -or $historicReportDate -ge $historicEndDate) { continue }
        $historicCurrentColumn = $historicBlockStartColumn + 4
        foreach ($link in $historicPoultryLinks) {
            $sourceDate = $historicReportDate.AddDays([int]$link.dateOffset)
            $dateFormula = "DATE($($sourceDate.Year),$($sourceDate.Month),$($sourceDate.Day))"
            $sourceSheetName = $workbook.Worksheets.Item([int]$link.sheetIndex).Name
            $dateRange = "'$sourceSheetName'!`$$($link.dateColumn)`$6:`$$($link.dateColumn)`$57"
            $valueRange = "'$sourceSheetName'!`$$($link.valueColumn)`$6:`$$($link.valueColumn)`$57"
            $availabilityRange = "'$sourceSheetName'!`$$($link.availabilityColumn)`$6:`$$($link.availabilityColumn)`$57"
            $lookup = "MATCH($dateFormula,$dateRange,0)"
            $sourceValue = "INDEX($valueRange,$lookup)"
            $availabilityValue = "INDEX($availabilityRange,$lookup)"
            $blank = '""'
            $historicFormula = "=IFERROR(IF($availabilityValue=$blank,$blank,$sourceValue),$blank)"
            try {
                $chickenEggReportSheet.Cells.Item([int]$link.targetRow, $historicCurrentColumn).Formula = $historicFormula
            } catch {
                throw "Unable to assign historical poultry report formula. row=$($link.targetRow), formula=$historicFormula, error=$($_.Exception.Message)"
            }
        }
    }

    # 표에 보이는 값과 증감률의 기준을 일치시킨다. 예를 들어 도축두수가
    # 146.129 → 143.675라면 표시값 146 → 144로 비교해 -1.4%가 된다.
    $reportComparisonMetrics = @(
        @{ row = 214; digits = 0 }, @{ row = 215; digits = 2 },
        @{ row = 221; digits = 0 }, @{ row = 222; digits = 2 },
        @{ row = 228; digits = 0 }, @{ row = 229; digits = 2 },
        @{ row = 235; digits = 2 }
    )
    $chickenEggComparisonMetrics = @(
        @{ row = 67; digits = 0 }, @{ row = 68; digits = 2 },
        @{ row = 74; digits = 2 }, @{ row = 80; digits = 0 },
        @{ row = 81; digits = 2 }, @{ row = 87; digits = 0 }
    )
    Set-DisplayedValueComparisonFormulas -Sheet $reportSheet -ReportDateRow 209 -Metrics $reportComparisonMetrics
    Set-DisplayedValueComparisonFormulas -Sheet $chickenEggReportSheet -ReportDateRow 62 -Metrics $chickenEggComparisonMetrics

    # 전주·전년 대비 색상은 과거 전체가 아니라 이번에 현행화하는 최근 주차
    # 블록에만 적용한다. 제목(전주·전년·대비)은 기본 글자색을 검정으로 둔다.
    $comparisonFormatTargets = @()
    foreach ($reportBlock in $reportBlocksForData) {
        $comparisonFormatTargets += @{
            sheet = $reportSheet
            clearTopRow = 211
            clearBottomRow = 236
            headerRows = @(212, 213, 219, 220, 226, 227, 233, 234)
            comparisonRows = @(214, 215, 221, 222, 228, 229, 235)
            blockStartColumn = [int]$reportBlock.startColumn
        }
    }
    for ($weeksBack = 0; $weeksBack -le 3; $weeksBack++) {
        $blockStartColumn = $chickenEggTargetStartColumn - (8 * $weeksBack)
        if ($blockStartColumn -lt 1) { break }
        $comparisonFormatTargets += @{
            sheet = $chickenEggReportSheet
            clearTopRow = 64
            clearBottomRow = 88
            headerRows = @(65, 66, 72, 73, 78, 79, 85, 86)
            comparisonRows = @(67, 68, 74, 80, 81, 87)
            blockStartColumn = $blockStartColumn
        }
    }
    $xlCellValue = 1
    $xlEqual = 3
    $xlGreater = 5
    $xlLess = 6
    foreach ($formatTarget in $comparisonFormatTargets) {
        $targetBlockStartColumn = [int]$formatTarget.blockStartColumn
        $comparisonColumns = @($targetBlockStartColumn + 5)
        $comparisonColumns += ($targetBlockStartColumn + 6)
        foreach ($comparisonColumn in $comparisonColumns) {
            try {
                # 이전 실행에서 남았을 수 있는 넓은 조건부 서식을 해당 주차 블록만
                # 제거한 뒤, 실제 퍼센트 데이터 행에만 다시 건다.
                $blockComparisonRange = $formatTarget.sheet.Range(
                    $formatTarget.sheet.Cells.Item([int]$formatTarget.clearTopRow, $comparisonColumn),
                    $formatTarget.sheet.Cells.Item([int]$formatTarget.clearBottomRow, $comparisonColumn)
                )
                $blockComparisonRange.FormatConditions.Delete()
                # 제목 행은 조건부 서식에서 제외해야 텍스트가 양수로 판정되어
                # 빨강으로 보이는 문제를 막을 수 있다.
                foreach ($headerRow in $formatTarget.headerRows) {
                    $headerCell = $formatTarget.sheet.Cells.Item([int]$headerRow, $comparisonColumn)
                    $headerCell.FormatConditions.Delete()
                    $headerCell.Font.Color = 0
                }
                foreach ($comparisonRow in $formatTarget.comparisonRows) {
                    $comparisonCell = $formatTarget.sheet.Cells.Item([int]$comparisonRow, $comparisonColumn)
                    $comparisonCell.Font.Color = 0
                    $positiveRule = $comparisonCell.FormatConditions.Add($xlCellValue, $xlGreater, '0')
                    # 양식에서 기존에 쓰던 기본 빨강·파랑 색상값을 그대로 사용한다.
                    $positiveRule.Font.Color = 255
                    $negativeRule = $comparisonCell.FormatConditions.Add($xlCellValue, $xlLess, '0')
                    $negativeRule.Font.Color = 16711680
                    $sameRule = $comparisonCell.FormatConditions.Add($xlCellValue, $xlEqual, '0')
                    $sameRule.Font.Color = 0
                }
            }
            catch {
                # 조건부 서식은 표시 보조 기능이다. 특정 양식의 병합 셀·기존 서식
                # 충돌로 실패해도 수집값·산식·보고서 저장은 중단하지 않는다.
                Write-Warning "비교율 색상 서식을 적용하지 못했습니다. sheet=$($formatTarget.sheet.Name), column=$comparisonColumn"
            }
        }
    }

    $excel.CalculateFull()
    # 마지막 전체 계산이 끝난 뒤 원래 계산 모드로 돌린 상태에서 저장한다.
    # 생성 파일을 사용자가 열었을 때 수동 계산 모드가 남지 않게 한다.
    if ($calculationOptimizationEnabled -and $null -ne $originalCalculation) { $excel.Calculation = $originalCalculation }
    # 돼지-EU 시트는 연도별 표가 매우 넓다. 이 시트만 고정 창을 해제해
    # 과거 연도까지 자유롭게 가로 스크롤할 수 있도록 한다.
    $euSheet = $workbook.Worksheets.Item(6)
    $euSheet.Activate()
    $excel.ActiveWindow.FreezePanes = $false
    $excel.ActiveWindow.SplitRow = 0
    $excel.ActiveWindow.SplitColumn = 0

    # 고정 창은 없지만, 파일을 처음 열 때는 이번에 현행화한 가장 최신 주차를
    # 바로 볼 수 있게 한다. 선택 셀은 LH(기준일)로 두어 앞뒤 데이터도 함께
    # 보이고, 이후에는 어느 연도로든 자유롭게 이동할 수 있다.
    $euPendingRows = @($pending | Where-Object { $_.market -eq 'eu_pork_germany' })
    if ($euPendingRows.Count -gt 0) {
        $latestEuRow = ($euPendingRows | ForEach-Object { [int]$_.row } | Measure-Object -Maximum).Maximum
        $latestEuCell = $euSheet.Range("LH$latestEuRow")
        $latestEuCell.Select()
        $excel.ActiveWindow.ScrollRow = [Math]::Max(1, $latestEuRow - 6)
        $excel.ActiveWindow.ScrollColumn = [Math]::Max(1, $latestEuCell.Column - 2)
    }
    else {
        $euSheet.Range('A1').Select()
        $excel.ActiveWindow.ScrollRow = 1
        $excel.ActiveWindow.ScrollColumn = 1
    }
    try {
        $workbook.SaveAs($OutputPath, 51)
    }
    catch {
        throw "Unable to save Excel output. path=$OutputPath, error=$($_.Exception.Message)"
    }
}
catch {
    $line = $_.InvocationInfo.ScriptLineNumber
    throw "Excel update failed at script line $line. $($_.Exception.Message)"
}
finally {
    if ($null -ne $workbook) { $workbook.Close($false) }
    if ($null -ne $excel) {
        try {
            if ($calculationOptimizationEnabled -and $null -ne $originalCalculation) { $excel.Calculation = $originalCalculation }
            if ($null -ne $originalEnableEvents) { $excel.EnableEvents = $originalEnableEvents }
            if ($null -ne $originalScreenUpdating) { $excel.ScreenUpdating = $originalScreenUpdating }
        }
        catch {
            # Excel 종료 직전의 응용 프로그램 설정 복원 실패는 생성본에 영향을 주지 않는다.
        }
        $excel.Quit()
    }
}
