import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [mode, ...arguments_] = process.argv.slice(2);

function excelSerialToIsoDate(serial) {
  const milliseconds = Date.UTC(1899, 11, 30) + Number(serial) * 86_400_000;
  return new Date(milliseconds).toISOString().slice(0, 10);
}

function addDays(isoDate, days) {
  const result = new Date(`${isoDate}T00:00:00Z`);
  result.setUTCDate(result.getUTCDate() + days);
  return result.toISOString().slice(0, 10);
}

async function loadTemplate(templatePath) {
  const input = await FileBlob.load(templatePath);
  return SpreadsheetFile.importXlsx(input);
}

const marketSheets = [
  { sheetName: "소-미국", dateColumn: "EO", currentColumn: "EQ", revisionColumn: "ER", priceColumn: "ES", kgPriceColumn: "ET", market: "beef" },
  { sheetName: "돼지-미국", dateColumn: "FD", currentColumn: "FF", revisionColumn: "FG", priceColumn: "FH", kgPriceColumn: "FI", market: "pork" },
];

if (mode === "pending") {
  const [templatePath, today] = arguments_;
  const workbook = await loadTemplate(templatePath);
  const pending = [];

  for (const config of marketSheets) {
    const sheet = workbook.worksheets.getItem(config.sheetName);
    const rows = sheet.getRange(`${config.dateColumn}8:${config.currentColumn}60`).values;
    for (const [index, values] of rows.entries()) {
      const row = index + 8;
      const [fridaySerial, , currentSlaughter] = values;
      if (typeof fridaySerial !== "number" || currentSlaughter !== null) continue;

      const friday = excelSerialToIsoDate(fridaySerial);
      const reportDate = addDays(friday, 5);
      if (reportDate <= today) pending.push({ ...config, row, reportDate });
    }
  }
  process.stdout.write(JSON.stringify(pending));
} else if (mode === "fill") {
  const [templatePath, outputPath, pendingPath, marketDataPath] = arguments_;
  const [pending, marketData] = await Promise.all([
    fs.readFile(pendingPath, "utf8").then(JSON.parse),
    fs.readFile(marketDataPath, "utf8").then(JSON.parse),
  ]);
  const dataByDate = new Map(marketData.map((item) => [item.reportDate, item]));
  const workbook = await loadTemplate(templatePath);

  for (const item of pending) {
    const data = dataByDate.get(item.reportDate);
    if (!data) continue;
    const sheet = workbook.worksheets.getItem(item.sheetName);
    const isPork = item.market === "pork";
    const [slaughterCount, previousSlaughterCount, cutoutPrice] = isPork
      ? [data.porkSlaughterCount, data.porkPreviousSlaughterCount, data.porkCutoutPrice]
      : [data.slaughterCount, data.previousSlaughterCount, data.cutoutPrice];

    sheet.getRange(`${item.currentColumn}${item.row}:${item.priceColumn}${item.row}`).values = [[
      slaughterCount,
      null,
      cutoutPrice,
    ]];

    const previousRow = item.row - 1;
    const recordedPreviousSlaughterCount = sheet.getRange(`${item.currentColumn}${previousRow}`).values[0][0];
    if (previousSlaughterCount !== null && previousSlaughterCount !== recordedPreviousSlaughterCount) {
      sheet.getRange(`${item.currentColumn}${previousRow}:${item.revisionColumn}${previousRow}`).values = [[
        previousSlaughterCount,
        recordedPreviousSlaughterCount,
      ]];
    }
    sheet.getRange(`${item.kgPriceColumn}${item.row}`).formulas = [[`=${item.priceColumn}${item.row}*2.20462`]];
  }

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
} else {
  throw new Error("Usage: template_report.mjs pending <template> <today> | fill <template> <output> <pending.json> <data.json>");
}
