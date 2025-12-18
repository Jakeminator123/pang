import { Workbook, type CellValue, type Worksheet } from "exceljs";

export type SheetCollection = Record<string, Record<string, unknown>[]>;

export type ParsedWorkbook = {
  sheets: SheetCollection;
  sheetNames: string[];
  rowCounts: Record<string, number>;
};

export async function parseExcelFile(filePath: string): Promise<ParsedWorkbook> {
  const workbook = new Workbook();
  await workbook.xlsx.readFile(filePath);

  const sheets: SheetCollection = {};

  workbook.worksheets.forEach((worksheet) => {
    sheets[worksheet.name] = worksheetToJson(worksheet);
  });

  const sheetNames = workbook.worksheets.map((sheet) => sheet.name);
  const rowCounts = Object.fromEntries(
    sheetNames.map((name) => [name, sheets[name]?.length ?? 0])
  );

  return {
    sheets,
    sheetNames,
    rowCounts,
  };
}

function worksheetToJson(worksheet: Worksheet): Record<string, unknown>[] {
  const rows: Record<string, unknown>[] = [];
  let headers: string[] = [];

  worksheet.eachRow({ includeEmpty: true }, (row, rowNumber) => {
    const values = row.values as CellValue[];

    if (rowNumber === 1) {
      headers = buildHeaders(values);
      return;
    }

    if (headers.length === 0) {
      return;
    }

    const rowData: Record<string, unknown> = {};
    headers.forEach((header, index) => {
      const cellValue = values[index + 1];
      rowData[header] = normalizeCellValue(cellValue);
    });

    const hasContent = Object.values(rowData).some(
      (value) => value !== null && value !== "" && value !== undefined
    );

    if (hasContent) {
      rows.push(rowData);
    }
  });

  return rows;
}

function buildHeaders(values: CellValue[]): string[] {
  return values.slice(1).map((value, index) => {
    const normalized = normalizeCellValue(value);
    const fallback = `Column ${index + 1}`;

    if (normalized === null || normalized === undefined || normalized === "") {
      return fallback;
    }

    return String(normalized).trim() || fallback;
  });
}

function normalizeCellValue(value: CellValue | undefined) {
  if (value === undefined || value === null) {
    return null;
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  if (typeof value === "object") {
    const anyValue = value as any;

    if ("text" in anyValue && typeof anyValue.text === "string") {
      return anyValue.text;
    }

    if ("result" in anyValue && anyValue.result !== undefined) {
      return anyValue.result;
    }

    if (Array.isArray(anyValue.richText)) {
      return anyValue.richText.map((part: any) => part.text).join("");
    }

    if ("hyperlink" in anyValue) {
      return anyValue.text ?? anyValue.hyperlink ?? null;
    }

    try {
      return JSON.stringify(anyValue);
    } catch {
      return String(anyValue);
    }
  }

  return value;
}

