import { NextRequest, NextResponse } from "next/server";
import { join } from "path";
import { existsSync } from "fs";
import { parseExcelFile } from "@/lib/excel";
import { PERSISTENT_DISK_DIR, LOCAL_DATA_DIR } from "@/lib/data-paths";

const JOCKE_API_KEY = process.env.JOCKE_API || "12345";

function verifyApiKey(request: NextRequest): boolean {
  // Check header first
  const headerKey = request.headers.get("X-API-Key") || request.headers.get("Authorization")?.replace("Bearer ", "");
  
  // Check query parameter
  const queryKey = request.nextUrl.searchParams.get("api_key");
  
  const providedKey = headerKey || queryKey;
  
  return providedKey === JOCKE_API_KEY;
}

export async function GET(request: NextRequest) {
  try {
    // Verify API key
    if (!verifyApiKey(request)) {
      return NextResponse.json(
        { error: "Unauthorized. Invalid or missing API key." },
        { status: 401 }
      );
    }

    // Get dates from query parameter
    const datesParam = request.nextUrl.searchParams.get("dates");
    
    if (!datesParam) {
      return NextResponse.json(
        { error: "Missing 'dates' parameter. Provide comma-separated dates (YYYYMMDD)." },
        { status: 400 }
      );
    }

    // Parse dates
    const dates = datesParam.split(",").map(d => d.trim()).filter(Boolean);
    
    if (dates.length === 0) {
      return NextResponse.json(
        { error: "No valid dates provided." },
        { status: 400 }
      );
    }

    // Validate date format
    const invalidDates = dates.filter(d => !/^\d{8}$/.test(d));
    if (invalidDates.length > 0) {
      return NextResponse.json(
        { error: `Invalid date format(s): ${invalidDates.join(", ")}. Use YYYYMMDD format.` },
        { status: 400 }
      );
    }

    // Fetch data for each date
    const results: Record<string, any> = {};
    const errors: Record<string, string> = {};

    for (const date of dates) {
      try {
        const persistentDateDir = join(PERSISTENT_DISK_DIR, date);
        const localDateDir = join(LOCAL_DATA_DIR, date);
        const dateDir = existsSync(persistentDateDir) ? persistentDateDir : localDateDir;
        const excelPath = join(dateDir, `kungorelser_${date}.xlsx`);
        const jockePath = join(dateDir, "jocke.xlsx");

        // Check if either file exists
        if (!existsSync(excelPath) && !existsSync(jockePath)) {
          errors[date] = "Data not found for this date";
          continue;
        }

        // Try jocke.xlsx first, fallback to kungorelser
        const filePath = existsSync(jockePath) ? jockePath : excelPath;
        const { sheets, sheetNames, rowCounts } = await parseExcelFile(filePath);

        results[date] = {
          date,
          file: existsSync(jockePath) ? "jocke.xlsx" : `kungorelser_${date}.xlsx`,
          sheets,
          sheetNames,
          rowCounts,
        };
      } catch (error: any) {
        errors[date] = error.message || "Failed to read data";
      }
    }

    return NextResponse.json({
      success: true,
      requestedDates: dates,
      data: results,
      errors: Object.keys(errors).length > 0 ? errors : undefined,
      summary: {
        totalDates: dates.length,
        successCount: Object.keys(results).length,
        errorCount: Object.keys(errors).length,
      },
    });
  } catch (error: any) {
    console.error("Error in JOCKE API:", error);
    return NextResponse.json(
      { error: "Internal server error", message: error.message },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    // Verify API key
    if (!verifyApiKey(request)) {
      return NextResponse.json(
        { error: "Unauthorized. Invalid or missing API key." },
        { status: 401 }
      );
    }

    // Get dates from body
    const body = await request.json().catch(() => ({}));
    const dates = body.dates || [];

    if (!Array.isArray(dates) || dates.length === 0) {
      return NextResponse.json(
        { error: "Missing 'dates' array in request body. Provide array of dates (YYYYMMDD)." },
        { status: 400 }
      );
    }

    // Validate date format
    const invalidDates = dates.filter((d: string) => !/^\d{8}$/.test(String(d).trim()));
    if (invalidDates.length > 0) {
      return NextResponse.json(
        { error: `Invalid date format(s): ${invalidDates.join(", ")}. Use YYYYMMDD format.` },
        { status: 400 }
      );
    }

    // Fetch data for each date
    const results: Record<string, any> = {};
    const errors: Record<string, string> = {};

    for (const date of dates) {
      const dateStr = String(date).trim();
      try {
        const persistentDateDir = join(PERSISTENT_DISK_DIR, dateStr);
        const localDateDir = join(LOCAL_DATA_DIR, dateStr);
        const dateDir = existsSync(persistentDateDir) ? persistentDateDir : localDateDir;
        const excelPath = join(dateDir, `kungorelser_${dateStr}.xlsx`);
        const jockePath = join(dateDir, "jocke.xlsx");

        // Check if either file exists
        if (!existsSync(excelPath) && !existsSync(jockePath)) {
          errors[dateStr] = "Data not found for this date";
          continue;
        }

        // Try jocke.xlsx first, fallback to kungorelser
        const filePath = existsSync(jockePath) ? jockePath : excelPath;
        const { sheets, sheetNames, rowCounts } = await parseExcelFile(filePath);

        results[dateStr] = {
          date: dateStr,
          file: existsSync(jockePath) ? "jocke.xlsx" : `kungorelser_${dateStr}.xlsx`,
          sheets,
          sheetNames,
          rowCounts,
        };
      } catch (error: any) {
        errors[dateStr] = error.message || "Failed to read data";
      }
    }

    return NextResponse.json({
      success: true,
      requestedDates: dates,
      data: results,
      errors: Object.keys(errors).length > 0 ? errors : undefined,
      summary: {
        totalDates: dates.length,
        successCount: Object.keys(results).length,
        errorCount: Object.keys(errors).length,
      },
    });
  } catch (error: any) {
    console.error("Error in JOCKE API:", error);
    return NextResponse.json(
      { error: "Internal server error", message: error.message },
      { status: 500 }
    );
  }
}

