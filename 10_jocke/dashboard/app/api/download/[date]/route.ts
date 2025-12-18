import { NextRequest, NextResponse } from "next/server";
import { createReadStream, statSync } from "fs";
import { isAuthenticated } from "@/lib/auth";
import { getZipPath } from "@/lib/data-paths";

export async function GET(
  request: NextRequest,
  { params }: { params: { date: string } }
) {
  try {
    // Check authentication
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

    const zipPath = await getZipPath(date);
    if (!zipPath) {
      return NextResponse.json(
        { error: "Zip file not found for this date" },
        { status: 404 }
      );
    }

    return serveZipFile(zipPath, date);
  } catch (error) {
    console.error("Error downloading zip:", error);
    return NextResponse.json(
      { error: "Failed to download file" },
      { status: 500 }
    );
  }
}

function serveZipFile(zipPath: string, date: string) {
  const stats = statSync(zipPath);
  const stream = createReadStream(zipPath);

  return new NextResponse(stream as any, {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="jocke_${date}.zip"`,
      "Content-Length": stats.size.toString(),
    },
  });
}
