import { join } from "path";
import { access, readdir } from "fs/promises";

// On Render: persistent disk at /var/data
// Locally: data_input folder in project root
export const PERSISTENT_DISK_DIR = "/var/data";
export const LOCAL_DATA_DIR = join(process.cwd(), "..", "data_input");
export const BUNDLES_DIR = join(process.cwd(), "..", "data_bundles");

export async function getExistingDateDir(date: string): Promise<string | null> {
  // Try persistent disk first (Render.com)
  const persistent = join(PERSISTENT_DISK_DIR, date);
  if (await pathExists(persistent)) return persistent;

  // Try local data_input folder
  const local = join(LOCAL_DATA_DIR, date);
  if (await pathExists(local)) return local;

  return null;
}

export async function getAllDateDirs(): Promise<string[]> {
  const dates = new Set<string>();

  // Check persistent disk
  if (await pathExists(PERSISTENT_DISK_DIR)) {
    const entries = await readdir(PERSISTENT_DISK_DIR, { withFileTypes: true }).catch(() => []);
    entries
      .filter((e) => e.isDirectory() && /^\d{8}$/.test(e.name))
      .forEach((e) => dates.add(e.name));
  }

  // Check local data_input
  if (await pathExists(LOCAL_DATA_DIR)) {
    const entries = await readdir(LOCAL_DATA_DIR, { withFileTypes: true }).catch(() => []);
    entries
      .filter((e) => e.isDirectory() && /^\d{8}$/.test(e.name))
      .forEach((e) => dates.add(e.name));
  }

  return Array.from(dates).sort((a, b) => b.localeCompare(a));
}

export async function getZipPath(date: string): Promise<string | null> {
  // Try in date directory first (after extraction or if zip already exists there)
  const dateDir = await getExistingDateDir(date);
  if (dateDir) {
    const zipInDir = join(dateDir, `${date}.zip`);
    if (await pathExists(zipInDir)) return zipInDir;
  }

  // Try in bundles directory (source zip files from git)
  const bundleZip = join(BUNDLES_DIR, `${date}.zip`);
  if (await pathExists(bundleZip)) return bundleZip;

  return null;
}

export async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}
