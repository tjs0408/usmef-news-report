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

if (mode === "pending") {
  const [templatePath, today] = arguments_;
  const workbook = await loadTemplate(templatePath);
  const sheet = workbook.worksheets.getItem("소-미국");
  const pending = [];
  const rows = sheet.getRange("EO8:EQ60").values;

  for (const [index, values] of rows.entries()) {
    const row = index + 8;
    const [fridaySerial, , currentSlaughter] = values;
    if (typeof fridaySerial !== "number" || currentSlaughter !== null) continue;

    const friday = excelSerialToIsoDate(fridaySerial);
    const reportDate = addDays(friday, 5);
    if (reportDate <= today) pending.push({ row, reportDate });
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
  const sheet = workbook.worksheets.getItem("소-미국");

  for (const item of pending) {
    const data = dataByDate.get(item.reportDate);
    if (!data) continue;
    sheet.getRange(`EQ${item.row}:ES${item.row}`).values = [[
      data.slaughterCount,
      data.previousSlaughterCount === data.slaughterCount ? null : data.previousSlaughterCount,
      data.cutoutPrice,
    ]];
  }

  workbook.recalculate();
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
} else {
  throw new Error("Usage: template_report.mjs pending <template> <today> | fill <template> <output> <pending.json> <data.json>");
}
