import { cookies } from "next/headers";

export async function verifyPassword(password: string): Promise<boolean> {
  // Simple password check - in production use proper hashing
  return password === "pang2024";
}

export async function isAuthenticated(): Promise<boolean> {
  try {
    const cookieStore = await cookies();
    const authCookie = cookieStore.get("pang_auth");
    return authCookie?.value === "authenticated";
  } catch {
    return false;
  }
}

export async function setAuthenticated() {
  const cookieStore = await cookies();
  cookieStore.set("pang_auth", "authenticated", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: "/",
  });
}

export async function clearAuth() {
  const cookieStore = await cookies();
  cookieStore.delete("pang_auth");
}

