[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TemplatePath,
    [Parameter(Mandatory = $true)]
    [string]$PayloadPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Release-ComObject {
    param([object]$Object)
    if ($null -ne $Object -and [System.Runtime.InteropServices.Marshal]::IsComObject($Object)) {
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($Object)
    }
}

function Get-TableControls {
    param([object]$Hwp)
    $result = New-Object System.Collections.ArrayList
    $control = $Hwp.HeadCtrl
    while ($null -ne $control) {
        if (([string]$control.CtrlID).Trim() -eq 'tbl') {
            [void]$result.Add($control)
        }
        $control = $control.Next
    }
    return $result.ToArray()
}

function Update-ReportTitleDate {
    param([object]$Hwp, [string]$TitleDateLabel)

    # 이 양식에는 1·2페이지 상단 제목의 날짜 '(8.20.)'가 네 번만 존재한다.
    # 본문이나 표의 날짜가 아닌 제목 안의 고정 양식 날짜만 치환한다.
    if ([string]::IsNullOrWhiteSpace($TitleDateLabel)) {
        throw 'The report title date is empty.'
    }
    $findReplace = $null
    try {
        $findReplace = $Hwp.HParameterSet.HFindReplace
        [void]$Hwp.HAction.GetDefault('AllReplace', $findReplace.HSet)
        $findReplace.Direction = $Hwp.FindDir('AllDoc')
        $findReplace.FindString = '(8.20.)'
        $findReplace.ReplaceString = $TitleDateLabel
        $findReplace.ReplaceMode = 1
        $findReplace.IgnoreMessage = 1
        $findReplace.FindType = 1
        if (-not $Hwp.HAction.Execute('AllReplace', $findReplace.HSet)) {
            throw 'Unable to update the HWP report title date.'
        }
    }
    finally {
        try { Release-ComObject $findReplace } catch {}
    }
}

function Enter-Table {
    param([object]$Hwp, [object]$TableControl)

    # GetAnchorPos → FindCtrl 순서가 없으면 표 안의 셀 이동 액션이 비활성화된다.
    try { [void]$Hwp.Run('Cancel') } catch {}
    try { [void]$Hwp.Run('MoveDocBegin') } catch {}
    $anchor = $null
    try {
        $anchor = $TableControl.GetAnchorPos(0)
        if (-not $Hwp.SetPosBySet($anchor)) {
            throw 'Unable to move to the table anchor.'
        }
        [void]$Hwp.FindCtrl()
        [void]$Hwp.HAction.Run('ShapeObjTableSelCell')
        [void]$Hwp.HAction.Run('Cancel')
    }
    finally {
        try { Release-ComObject $anchor } catch {}
    }
}

function Get-TableDataCellRoute {
    # 각 경로는 바로 이전 데이터 셀에서 다음 데이터 셀로 이동하는 순서다.
    # 첫 경로만 표 좌상단(R0C0)에서 시작한다.
    return @(
        @{ key = '3,2'; actions = @('TableLowerCell', 'TableRightCell', 'TableLowerCell') }
        @{ key = '3,3'; actions = @('TableRightCell') }
        @{ key = '3,4'; actions = @('TableRightCell') }
        @{ key = '4,2'; actions = @('TableLowerCell', 'TableLeftCell', 'TableLeftCell') }
        @{ key = '4,3'; actions = @('TableRightCell') }
        @{ key = '4,4'; actions = @('TableRightCell') }
        @{ key = '4,5'; actions = @('TableRightCell') }
        @{ key = '4,6'; actions = @('TableRightCell') }
        @{ key = '5,2'; actions = @('TableLowerCell', 'TableLeftCell', 'TableLeftCell', 'TableLeftCell', 'TableLeftCell') }
        @{ key = '5,3'; actions = @('TableRightCell') }
        @{ key = '5,4'; actions = @('TableRightCell') }
        @{ key = '5,5'; actions = @('TableRightCell') }
        @{ key = '5,6'; actions = @('TableRightCell') }
        @{ key = '6,2'; actions = @('TableLowerCell', 'TableLeftCell', 'TableLeftCell', 'TableLeftCell', 'TableLeftCell') }
        @{ key = '6,3'; actions = @('TableRightCell') }
        @{ key = '6,4'; actions = @('TableRightCell') }
    )
}

function Set-TableDataCells {
    param([object]$Hwp, [object]$TableControl, [object[]]$Cells)

    $cellMap = @{}
    foreach ($cell in $Cells) {
        $cellMap["$([int]$cell.row),$([int]$cell.column)"] = $cell
    }
    Enter-Table -Hwp $Hwp -TableControl $TableControl
    $routes = @(Get-TableDataCellRoute)
    $lastRouteIndex = -1
    for ($index = 0; $index -lt $routes.Count; $index++) {
        if ($cellMap.ContainsKey($routes[$index].key)) {
            $lastRouteIndex = $index
        }
    }
    if ($lastRouteIndex -lt 0) {
        return
    }
    for ($routeIndex = 0; $routeIndex -le $lastRouteIndex; $routeIndex++) {
        $route = $routes[$routeIndex]
        foreach ($action in $route.actions) {
            if (-not $Hwp.HAction.Run($action)) {
                throw "Unable to move to HWP table cell. cell=$($route.key), action=$action"
            }
        }
        if ($cellMap.ContainsKey($route.key)) {
            $cell = $cellMap[$route.key]
            $comparisonColor = if ($null -ne $cell.comparisonColor) { [string]$cell.comparisonColor } else { '' }
            Set-CurrentCellText -Hwp $Hwp -Text ([string]$cell.value) -ComparisonColor $comparisonColor
            try { [void]$Hwp.Run('Cancel') } catch {}
        }
    }
}

function Set-CurrentCellText {
    param(
        [object]$Hwp,
        [AllowEmptyString()][string]$Text,
        [AllowEmptyString()][string]$ComparisonColor = ''
    )

    # 데이터 셀은 한 문단이므로 현재 문단의 텍스트만 선택한다. Delete 후
    # InsertText를 사용해 셀 테두리·배경·정렬은 유지한다.
    [void]$Hwp.Run('MoveParaBegin')
    [void]$Hwp.Run('MoveSelParaEnd')
    [void]$Hwp.Run('Delete')
    if ([string]::IsNullOrEmpty($Text)) {
        return
    }
    $set = $null
    try {
        $set = $Hwp.HParameterSet.HInsertText
        [void]$Hwp.HAction.GetDefault('InsertText', $set.HSet)
        $set.Text = $Text
        if (-not $Hwp.HAction.Execute('InsertText', $set.HSet)) {
            throw 'Unable to insert HWP table cell text.'
        }
    }
    finally {
        try { Release-ComObject $set } catch {}
    }

    if (-not [string]::IsNullOrEmpty($ComparisonColor)) {
        Set-CurrentCellComparisonColor -Hwp $Hwp -ColorName $ComparisonColor
    }
}

function Set-CurrentCellComparisonColor {
    param([object]$Hwp, [string]$ColorName)

    # 한글 원본 양식의 기존 비교 색상: 빨강 #FF0000, 파랑 #0000FF, 검정 #000000.
    $rgb = switch ($ColorName) {
        'red' { $Hwp.RGBColor(255, 0, 0); break }
        'blue' { $Hwp.RGBColor(0, 0, 255); break }
        default { $Hwp.RGBColor(0, 0, 0); break }
    }

    # 방금 입력한 셀의 문단만 선택해 글자색만 바꾼다. 셀 배경·테두리·정렬은 유지된다.
    [void]$Hwp.Run('MoveParaBegin')
    [void]$Hwp.Run('MoveSelParaEnd')
    $shape = $null
    try {
        $shape = $Hwp.HParameterSet.HCharShape
        [void]$Hwp.HAction.GetDefault('CharShape', $shape.HSet)
        $shape.TextColor = $rgb
        if (-not $Hwp.HAction.Execute('CharShape', $shape.HSet)) {
            throw 'Unable to set HWP comparison text color.'
        }
    }
    finally {
        try { Release-ComObject $shape } catch {}
    }
}

if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
    throw "HWP template not found: $TemplatePath"
}
if (-not (Test-Path -LiteralPath $PayloadPath -PathType Leaf)) {
    throw "HWP payload not found: $PayloadPath"
}

$payload = Get-Content -LiteralPath $PayloadPath -Raw -Encoding UTF8 | ConvertFrom-Json
$workingDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("weekly_hwp_" + [guid]::NewGuid().ToString('N'))
$inputCopy = Join-Path $workingDirectory 'input.hwp'
$temporaryOutput = Join-Path $workingDirectory 'output.hwp'
$hwp = $null
$verifyHwp = $null

try {
    New-Item -ItemType Directory -Path $workingDirectory -Force | Out-Null
    Copy-Item -LiteralPath $TemplatePath -Destination $inputCopy -Force
    $hwp = New-Object -ComObject HWPFrame.HwpObject
    try { [void]$hwp.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule') } catch {}
    $hwp.XHwpWindows.Item(0).Visible = $false
    $opened = $hwp.Open($inputCopy, 'HWP', 'forceopen:true;versionwarning:false;suspendpassword:false')
    if (-not $opened) {
        throw 'Unable to open the HWP template.'
    }

    Update-ReportTitleDate -Hwp $hwp -TitleDateLabel ([string]$payload.titleDateLabel)

    foreach ($tableUpdate in $payload.tables) {
        $tableIndex = [int]$tableUpdate.tableIndex
        $tables = Get-TableControls -Hwp $hwp
        if ($tableIndex -lt 0 -or $tableIndex -ge $tables.Count) {
            throw "The HWP template table layout has changed. tableIndex=$tableIndex"
        }
        $tableControl = $tables[$tableIndex]
        try {
            Set-TableDataCells -Hwp $hwp -TableControl $tableControl -Cells @($tableUpdate.cells)
        }
        finally {
            foreach ($table in $tables) {
                try { Release-ComObject $table } catch {}
            }
        }
    }

    if (-not $hwp.SaveAs($temporaryOutput, 'HWP', '')) {
        throw 'Unable to save the HWP report.'
    }
    try { $hwp.Clear(1) } catch {}
    $hwp.Quit()
    Release-ComObject $hwp
    $hwp = $null

    # 저장본을 다시 열어 HWP 자체가 정상적으로 읽을 수 있는지 확인한다.
    $verifyHwp = New-Object -ComObject HWPFrame.HwpObject
    try { [void]$verifyHwp.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule') } catch {}
    $verifyHwp.XHwpWindows.Item(0).Visible = $false
    if (-not $verifyHwp.Open($temporaryOutput, 'HWP', 'forceopen:true;versionwarning:false;suspendpassword:false')) {
        throw 'Unable to reopen the saved HWP report.'
    }
    try { $verifyHwp.Clear(1) } catch {}
    $verifyHwp.Quit()
    Release-ComObject $verifyHwp
    $verifyHwp = $null

    Copy-Item -LiteralPath $temporaryOutput -Destination $OutputPath -Force
    Write-Output ('HWP_REPORT_SAVED=' + $OutputPath)
}
finally {
    if ($null -ne $verifyHwp) {
        try { $verifyHwp.Clear(1) } catch {}
        try { $verifyHwp.Quit() } catch {}
        try { Release-ComObject $verifyHwp } catch {}
    }
    if ($null -ne $hwp) {
        try { $hwp.Clear(1) } catch {}
        try { $hwp.Quit() } catch {}
        try { Release-ComObject $hwp } catch {}
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    if (Test-Path -LiteralPath $workingDirectory) {
        Remove-Item -LiteralPath $workingDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
