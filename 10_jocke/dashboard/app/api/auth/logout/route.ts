import { NextResponse } from "next/server";
import { clearAuth } from "@/lib/auth";

export async function POST() {
  await clearAuth();
  return NextResponse.json({ success: true });
}

