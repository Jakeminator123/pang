import { NextRequest, NextResponse } from "next/server";
import { join } from "path";
import { existsSync } from "fs";
import { isAuthenticated } from "@/lib/auth";
import Database from "better-sqlite3";
import { parseExcelFile } from "@/lib/excel";
import { getExistingDateDir } from "@/lib/data-paths";

export async function GET(
  request: NextRequest,
  { params }: { params: { date: string } }
) {
  try {
    const authenticated = await isAuthenticated();
    if (!authenticated) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const { date } = params;

    if (!/^\d{8}$/.test(date)) {
      return NextResponse.json(
        { error: "Invalid date format" },
        { status: 400 }
      );
    }

    const dateDir = await getExistingDateDir(date);
    if (!dateDir) {
      return NextResponse.json(
        { error: "Data not found for this date" },
        { status: 404 }
      );
    }

    const dbPath = join(dateDir, "data.db");
    const excelPath = join(dateDir, `kungorelser_${date}.xlsx`);
    const jockePath = join(dateDir, "jocke.xlsx");

    // Try SQLite first, fallback to Excel
    if (existsSync(dbPath)) {
      return getDataFromSQLite(dbPath, date);
    } else if (existsSync(jockePath) || existsSync(excelPath)) {
      const filePath = existsSync(jockePath) ? jockePath : excelPath;
      return await getDataFromExcel(filePath, date);
    } else {
      return NextResponse.json(
        { error: "Data not found for this date" },
        { status: 404 }
      );
    }
  } catch (error) {
    console.error("Error reading data:", error);
    return NextResponse.json({ error: "Failed to read data" }, { status: 500 });
  }
}

function getDataFromSQLite(dbPath: string, date: string) {
  try {
    const db = new Database(dbPath, { readonly: true });

    // Get companies
    const companies = db.prepare("SELECT * FROM companies").all();

    // Get people
    const people = db.prepare("SELECT * FROM people").all();

    // Get company details
    const companyDetails = db.prepare("SELECT * FROM company_details").all();

    // Calculate stats
    const stats = {
      totalCompanies: companies.length,
      totalPeople: people.length,
      hasPeopleData: people.length > 0,
      companiesWithDomain: companies.filter((c: any) => c.domain_verified === 1)
        .length,
      companiesWithEmail: companies.filter(
        (c: any) => c.emails && c.emails.trim() !== ""
      ).length,
      companiesWithPhone: companies.filter((c: any) => c.phones_found > 0)
        .length,
      uniquePeople: new Set(
        people.map((p: any) => p.personnummer).filter(Boolean)
      ).size,
      boardMembers: people.filter(
        (p: any) =>
          p.roll === "Styrelseledamot" || p.titel?.includes("Styrelseledamot")
      ).length,
      deputies: people.filter(
        (p: any) =>
          p.roll === "Styrelsesuppleant" ||
          p.titel?.includes("Styrelsesuppleant")
      ).length,
      uniqueCities: new Set(people.map((p: any) => p.ort).filter(Boolean)).size,
      segments: {} as Record<string, number>,
    };

    // Count segments
    companies.forEach((c: any) => {
      const segment = c.segment || "Unknown";
      stats.segments[segment] = (stats.segments[segment] || 0) + 1;
    });

    db.close();

    return NextResponse.json({
      date,
      stats,
      sheets: {
        Huvuddata: companies,
        Personer: people,
        CompanyDetails: companyDetails,
      },
      sheetNames: ["Huvuddata", "Personer", "CompanyDetails"],
      source: "sqlite",
    });
  } catch (error: any) {
    console.error("Error reading SQLite:", error);
    throw error;
  }
}

async function getDataFromExcel(filePath: string, date: string) {
  const { sheets, sheetNames } = await parseExcelFile(filePath);
  const mainSheetName = sheetNames[0];
  const mainSheet = (mainSheetName ? sheets[mainSheetName] : []) as any[];
  const peopleSheet = (sheets["Personer"] ?? []) as any[];

  const stats = {
    totalCompanies: mainSheet.length,
    totalPeople: peopleSheet.length,
    hasPeopleData: peopleSheet.length > 0,
    companiesWithDomain: mainSheet.filter(
      (c: any) => c.domain_verified === true || c.domain_verified === "true"
    ).length,
    companiesWithEmail: mainSheet.filter(
      (c: any) => c["E-post"] && String(c["E-post"]).trim() !== ""
    ).length,
    companiesWithPhone: mainSheet.filter(
      (c: any) => c.phones_found && Number(c.phones_found) > 0
    ).length,
    uniquePeople: new Set(
      peopleSheet.map((p: any) => p.personnummer).filter(Boolean)
    ).size,
    boardMembers: peopleSheet.filter(
      (p: any) =>
        p.roll === "Styrelseledamot" || p.titel?.includes("Styrelseledamot")
    ).length,
    deputies: peopleSheet.filter(
      (p: any) =>
        p.roll === "Styrelsesuppleant" || p.titel?.includes("Styrelsesuppleant")
    ).length,
    uniqueCities: new Set(peopleSheet.map((p: any) => p.ort).filter(Boolean))
      .size,
    segments: {} as Record<string, number>,
  };

  mainSheet.forEach((c: any) => {
    const segment = c.Segment || "Unknown";
    stats.segments[segment] = (stats.segments[segment] || 0) + 1;
  });

  return NextResponse.json({
    date,
    stats,
    sheets,
    sheetNames,
    source: "excel",
  });
}
