import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { getAllDateDirs } from "@/lib/data-paths";

export async function GET() {
  try {
    const authenticated = await isAuthenticated();
    if (!authenticated) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const dates = await getAllDateDirs();
    const dateFolders = dates.map((date) => ({
      date,
      formatted: `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`,
    }));

    return NextResponse.json({ dates: dateFolders });
  } catch (error) {
    console.error("Error reading dates:", error);
    return NextResponse.json(
      { error: "Failed to read dates" },
      { status: 500 }
    );
  }
}
