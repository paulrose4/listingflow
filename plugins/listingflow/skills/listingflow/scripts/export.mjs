// Read-only optional previews. Production Excel serialization is lf_excel.py.
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

let artifact;
try {
  if (process.env.LISTINGFLOW_NODE_MODULES) {
    const req = createRequire(path.join(path.resolve(process.env.LISTINGFLOW_NODE_MODULES), "..", "listingflow-runtime.cjs"));
    artifact = await import(pathToFileURL(req.resolve("@oai/artifact-tool")).href);
  } else {
    artifact = await import("@oai/artifact-tool");
  }
} catch {
  throw new Error("Optional preview unavailable: configure LISTINGFLOW_NODE_MODULES; do not auto-install globally.");
}
const { Workbook, SpreadsheetFile, FileBlob } = artifact;
if (process.argv[2] === "--probe") {
  const wb = Workbook.create();
  wb.worksheets.add("Probe");
  console.log(JSON.stringify({ ok: true, engine: "@oai/artifact-tool", node: process.version }));
  process.exit(0);
}
const outputDir = path.resolve(process.argv[2]);
const request = JSON.parse(await fs.readFile(path.join(outputDir, "export.json"), "utf8"));
for (const name of ["文案", "自查"]) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(outputDir, `${name}.xlsx`)));
  for (const sheet of wb.worksheets.items) {
    // The renderer import infers numeric-looking strings despite XLSX text typing.
    // Repair the preview projection only; never resave or alter the verified workbook.
    if (sheet.name === "文案" || sheet.name === "版本") {
      const skuCell = sheet.getRange(sheet.name === "文案" ? "B3" : "B4");
      if (/^\d+$/u.test(request.sku)) {
        skuCell.values = [[0]];
        skuCell.setNumberFormat(`"${request.sku}"`);
      } else {
        skuCell.values = [[request.sku]];
      }
      skuCell.format.horizontalAlignment = "left";
    }
    const v3 = (request.workflow_version ?? 1) >= 3;
    const range = request.report_layout === "operator-overview-v1" && sheet.name === "处理清单" ? "A1:I6" : v3 ? ({
      "审核结论": "A1:F18", "已处理与可选": "A1:F6",
      "处理清单": "A1:H8", "内容检查": "A1:E7", "来源依据": "A1:F7",
      "规则与范围": "A1:C8", "文案": "A1:B12", "版本": "A1:B11",
      "违禁词自查表": "A1:F7", "侵权词自查表": "A1:F8",
      "本地化自查表": "A1:F7", "文案合规自查表": "A1:F8",
    }[sheet.name] ?? "A1:F8") : sheet.name === "处理清单" ? "A1:D7" : sheet.name === "版本" ? "A1:B11" : sheet.name === "文案" ? "A1:C12" :
      sheet.name === "自查" ? "A1:G10" : "A1:F8";
    const image = await wb.render({ sheetName: sheet.name, range, scale: 1, format: "png" });
    await fs.writeFile(path.join(outputDir, `${name}-${sheet.name}.png`), new Uint8Array(await image.arrayBuffer()));
    if (request.research_version === 1 && name === "自查" && sheet.name === "本地化自查表") {
      const researchImage = await wb.render({ sheetName: sheet.name, range: "A8:F23", scale: 1, format: "png" });
      await fs.writeFile(path.join(outputDir, "自查-关键词调研明细.png"), new Uint8Array(await researchImage.arrayBuffer()));
    }
  }
}
console.log(JSON.stringify({ preview_complete: true }));
