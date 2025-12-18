/**
 * Setup script for Render deployment.
 * Extracts zip files from data_bundles/ to /var/data on persistent disk.
 * Run this before starting the server.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const BUNDLES_DIR = path.join(__dirname, '..', '..', 'data_bundles');
const PERSISTENT_DISK = '/var/data';

function extractZips() {
  console.log('Setting up data on persistent disk...\n');
  
  // Check if persistent disk exists (Render.com)
  if (!fs.existsSync(PERSISTENT_DISK)) {
    console.log('Persistent disk not found at /var/data');
    console.log('This is expected in local development.\n');
    return;
  }
  
  // Check if bundles directory exists
  if (!fs.existsSync(BUNDLES_DIR)) {
    console.log('No data_bundles/ directory found.');
    console.log('Run: cd data_input && python zip_folders.py\n');
    return;
  }
  
  // Find all zip files
  const zipFiles = fs.readdirSync(BUNDLES_DIR)
    .filter(f => f.endsWith('.zip') && /^\d{8}\.zip$/.test(f));
  
  if (zipFiles.length === 0) {
    console.log('No date zip files found in data_bundles/');
    return;
  }
  
  console.log(`Found ${zipFiles.length} zip file(s) to extract:\n`);
  
  for (const zipFile of zipFiles) {
    const date = zipFile.replace('.zip', '');
    const zipPath = path.join(BUNDLES_DIR, zipFile);
    const targetDir = path.join(PERSISTENT_DISK, date);
    
    // Check if already extracted
    if (fs.existsSync(targetDir)) {
      const files = fs.readdirSync(targetDir);
      if (files.length > 0) {
        console.log(`  ${date}/ already exists with ${files.length} files, skipping`);
        continue;
      }
    }
    
    // Create target directory
    fs.mkdirSync(targetDir, { recursive: true });
    
    // Extract zip using unzip command
    console.log(`  Extracting ${zipFile} to ${targetDir}`);
    try {
      execSync(`unzip -o "${zipPath}" -d "${targetDir}"`, { stdio: 'inherit' });
      
      // Copy zip file to target directory for download endpoint
      const targetZipPath = path.join(targetDir, zipFile);
      if (!fs.existsSync(targetZipPath)) {
        fs.copyFileSync(zipPath, targetZipPath);
        console.log(`  ✓ Copied ${zipFile} to ${date}/ for downloads`);
      }
      
      console.log(`  ✓ Extracted ${date}/\n`);
    } catch (error) {
      console.error(`  ✗ Failed to extract ${zipFile}:`, error.message);
    }
  }
  
  console.log('\nData setup complete!');
  
  // List what's on the persistent disk
  console.log('\nContents of /var/data:');
  const dirs = fs.readdirSync(PERSISTENT_DISK);
  dirs.forEach(d => {
    const fullPath = path.join(PERSISTENT_DISK, d);
    if (fs.statSync(fullPath).isDirectory()) {
      const files = fs.readdirSync(fullPath);
      console.log(`  ${d}/ (${files.length} files)`);
    }
  });
}

extractZips();

