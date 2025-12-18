"""
Batch generator for creating preview sites for multiple companies.
Generates sites using v0 Platform API and saves preview URLs and cost metadata.
"""

import json
import os
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Add current directory (all_the_scripts) to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from generator import (
        generate_preview_v0,
        extract_company_data,
        build_v0_prompt,
        DEFAULT_V0_API_KEY,
        DEFAULT_OPENAI_API_KEY,
        DEFAULT_UNSPLASH_ACCESS_KEY,
        DEFAULT_PEXELS_API_KEY,
    )
    from v0_client import V0Client, DEFAULT_MODEL
    from cost_tracker import estimate_v0_cost, create_cost_entry
    from screenshot import take_screenshot_simple
except ImportError:
    try:
        from .generator import (
            generate_preview_v0,
            extract_company_data,
            build_v0_prompt,
            DEFAULT_V0_API_KEY,
            DEFAULT_OPENAI_API_KEY,
            DEFAULT_UNSPLASH_ACCESS_KEY,
            DEFAULT_PEXELS_API_KEY,
        )
        from .v0_client import V0Client, DEFAULT_MODEL
        from .cost_tracker import estimate_v0_cost, create_cost_entry
        from .screenshot import take_screenshot_simple
    except ImportError as e:
        raise ImportError(
            f"Could not import required modules: {e}. "
            "Make sure generator.py, v0_client.py, and cost_tracker.py exist."
        )


def save_preview_url(folder_path: Path, preview_url: str, metadata: Dict[str, Any]):
    """Save preview URL and metadata to company folder."""
    # Save simple preview URL file
    preview_url_file = folder_path / "preview_url.txt"
    preview_url_file.write_text(preview_url, encoding="utf-8")
    
    # Save detailed metadata
    metadata_file = folder_path / "site_metadata.json"
    metadata_file.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    
    print(f"✅ Saved preview URL to {folder_path.name}")


async def save_screenshot(folder_path: Path, preview_url: str) -> bool:
    """Take and save screenshot of preview site."""
    screenshot_path = folder_path / "preview_screenshot.png"
    try:
        success = await take_screenshot_simple(preview_url, screenshot_path)
        if success:
            print(f"📸 Saved screenshot to {screenshot_path.name}")
        return success
    except Exception as e:
        print(f"⚠️  Could not take screenshot: {e}")
        return False


async def generate_site_for_company(
    folder_name: str,
    base_dir: Path,
    v0_api_key: Optional[str] = None,
    openai_key: Optional[str] = None,
    use_openai_enhancement: bool = True,
    use_images: bool = True,
    fetch_actual_costs: bool = True,
) -> Dict[str, Any]:
    """
    Generate site for a single company and return result with cost info.
    
    Args:
        folder_name: Name of the company folder (e.g., "K928253-25")
        base_dir: Base directory containing the company folder (should be the date folder, e.g., .../djupanalys/20251208)
    
    Returns:
        Dict with preview_url, demo_url, cost_info, and metadata
    """
    # Ensure base_dir is a Path object
    if not isinstance(base_dir, Path):
        base_dir = Path(base_dir)
    
    folder_path = base_dir / folder_name
    
    if not folder_path.exists():
        raise FileNotFoundError(
            f"Company folder not found: {folder_path}\n"
            f"  base_dir: {base_dir}\n"
            f"  folder_name: {folder_name}\n"
            f"  Expected path: {folder_path}\n"
            f"  base_dir exists: {base_dir.exists()}\n"
            f"  base_dir contents: {list(base_dir.iterdir()) if base_dir.exists() else 'N/A'}"
        )
    
    # Extract company data
    data = extract_company_data(folder_path)
    
    # Get API keys
    v0_key = v0_api_key or os.getenv("V0_API_KEY") or DEFAULT_V0_API_KEY
    openai_key_final = (
        openai_key or os.getenv("OPENAI_API_KEY") or DEFAULT_OPENAI_API_KEY
    )
    unsplash_key_final = (
        os.getenv("UNSPLASH_ACCESS_KEY") or DEFAULT_UNSPLASH_ACCESS_KEY
    )
    pexels_key_final = (
        os.getenv("PEXELS_API_KEY") or DEFAULT_PEXELS_API_KEY
    )
    
    # Build prompt
    prompt = await build_v0_prompt(
        data,
        use_openai=use_openai_enhancement,
        use_images=use_images,
        openai_key=openai_key_final,
        unsplash_key=unsplash_key_final,
        pexels_key=pexels_key_final,
    )
    
    # Estimate cost before generation
    estimated_cost = estimate_v0_cost(prompt, DEFAULT_MODEL)
    
    # Generate with v0
    print(f"🔄 Generating site for {data['company_name']} ({folder_name})...")
    v0_result = await generate_preview_v0(
        folder_name,
        base_dir=base_dir,
        v0_api_key=v0_key,
        openai_key=openai_key_final,
        use_openai_enhancement=use_openai_enhancement,
        use_images=use_images,
    )
    
    demo_url = v0_result.get("demoUrl")
    chat_id = v0_result.get("chatId")
    
    if not demo_url:
        raise ValueError(f"Failed to generate demo URL for {folder_name}")
    
    # Try to fetch actual usage/cost
    actual_usage = None
    if fetch_actual_costs and chat_id:
        print(f"  📊 Fetching actual usage data...")
        # Wait a bit for usage data to be available
        await asyncio.sleep(3)
        try:
            client = V0Client(v0_key)
            usage_data = await client.get_usage(chat_id=chat_id)
            events = usage_data.get("events", [])
            for event in events:
                if event.get("chatId") == chat_id:
                    actual_usage = {
                        "actual_cost_usd": event.get("cost", 0),
                        "actual_tokens": event.get("tokens", 0),
                        "model": event.get("model", DEFAULT_MODEL),
                        "timestamp": event.get("timestamp"),
                    }
                    break
        except Exception as e:
            print(f"  ⚠️  Could not fetch actual usage: {e}")
    
    # Build cost info using cost tracker
    cost_info = create_cost_entry(estimated_cost, actual_usage)
    
    # Build metadata
    metadata = {
        "company_name": data["company_name"],
        "orgnr": data["orgnr"],
        "folder_name": folder_name,
        "preview_url": demo_url,
        "chat_id": chat_id,
        "version_id": v0_result.get("versionId"),
        "cost": cost_info,
        "generated_at": datetime.now().isoformat(),
    }
    
    # Save to company folder
    save_preview_url(folder_path, demo_url, metadata)
    
    # Take screenshot (optional, won't fail if it doesn't work)
    try:
        await save_screenshot(folder_path, demo_url)
    except Exception as e:
        print(f"  ⚠️  Screenshot skipped: {e}")
    
    return {
        "success": True,
        "folder_name": folder_name,
        "company_name": data["company_name"],
        "preview_url": demo_url,
        "chat_id": chat_id,
        "cost_info": cost_info,
        "metadata": metadata,
    }


async def batch_generate_sites(
    companies_dir: Path,
    output_metadata_file: Optional[Path] = None,
    v0_api_key: Optional[str] = None,
    openai_key: Optional[str] = None,
    use_openai_enhancement: bool = True,
    use_images: bool = True,
    fetch_actual_costs: bool = True,
) -> Dict[str, Any]:
    """
    Generate sites for all companies in the directory.
    
    Args:
        companies_dir: Directory containing company folders
        output_metadata_file: Path to save batch metadata (defaults to 3_sajt/batch_metadata.json)
        v0_api_key: v0 API key (optional, uses env/default)
        openai_key: OpenAI API key (optional, uses env/default)
        use_openai_enhancement: Whether to enhance prompts with OpenAI
        use_images: Whether to search and include images
        fetch_actual_costs: Whether to fetch actual costs from v0 API
    
    Returns:
        Dict with results for all companies
    """
    if not companies_dir.exists():
        raise FileNotFoundError(f"Companies directory not found: {companies_dir}")
    
    # Find all company folders (folders starting with K and containing numbers)
    company_folders = [
        d
        for d in companies_dir.iterdir()
        if d.is_dir() and d.name.startswith("K") and d.name.endswith("-25")
    ]
    
    if not company_folders:
        raise ValueError(f"No company folders found in {companies_dir}")
    
    print(f"📁 Found {len(company_folders)} company folders")
    print(f"🚀 Starting batch generation...\n")
    
    results = []
    total_estimated_cost = 0.0
    total_actual_cost = 0.0
    
    # Process companies sequentially to avoid rate limits
    for i, folder_path in enumerate(company_folders, 1):
        folder_name = folder_path.name
        print(f"\n[{i}/{len(company_folders)}] Processing {folder_name}...")
        
        try:
            result = await generate_site_for_company(
                folder_name,
                companies_dir,
                v0_api_key=v0_api_key,
                openai_key=openai_key,
                use_openai_enhancement=use_openai_enhancement,
                use_images=use_images,
                fetch_actual_costs=fetch_actual_costs,
            )
            
            results.append(result)
            
            # Accumulate costs
            cost_info = result["cost_info"]
            total_estimated_cost += cost_info["estimated"]["estimated_cost_usd"]
            if cost_info.get("actual"):
                total_actual_cost += cost_info["actual"].get("actual_cost_usd", 0)
            
            print(f"✅ Success: {result['preview_url']}")
            
            # Small delay to avoid rate limits
            if i < len(company_folders):
                await asyncio.sleep(2)
        
        except Exception as e:
            error_result = {
                "success": False,
                "folder_name": folder_name,
                "error": str(e),
                "generated_at": datetime.now().isoformat(),
            }
            results.append(error_result)
            print(f"❌ Error: {e}")
    
    # Build batch metadata
    batch_metadata = {
        "generated_at": datetime.now().isoformat(),
        "companies_dir": str(companies_dir),
        "total_companies": len(company_folders),
        "successful": len([r for r in results if r.get("success")]),
        "failed": len([r for r in results if not r.get("success")]),
        "total_estimated_cost_usd": round(total_estimated_cost, 6),
        "total_actual_cost_usd": round(total_actual_cost, 6) if total_actual_cost > 0 else None,
        "results": results,
    }
    
    # Save batch metadata
    if output_metadata_file is None:
        output_metadata_file = Path(__file__).parent.parent / "batch_metadata.json"
    
    output_metadata_file.write_text(
        json.dumps(batch_metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    
    print(f"\n{'='*60}")
    print(f"📊 Batch Generation Summary")
    print(f"{'='*60}")
    print(f"Total companies: {len(company_folders)}")
    print(f"Successful: {batch_metadata['successful']}")
    print(f"Failed: {batch_metadata['failed']}")
    print(f"Total estimated cost: ${total_estimated_cost:.4f} USD")
    if total_actual_cost > 0:
        print(f"Total actual cost: ${total_actual_cost:.4f} USD")
    print(f"\nMetadata saved to: {output_metadata_file}")
    print(f"{'='*60}\n")
    
    return batch_metadata


async def main():
    """Main entry point for batch generation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Batch generate preview sites for companies"
    )
    parser.add_argument(
        "--companies-dir",
        type=str,
        default=None,
        help="Directory containing company folders (default: 2_segment_info/djupanalys/20251208)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output metadata file path (default: 3_sajt/batch_metadata.json)",
    )
    parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Disable OpenAI prompt enhancement",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Disable image search",
    )
    parser.add_argument(
        "--no-actual-costs",
        action="store_true",
        help="Skip fetching actual costs from v0 API",
    )
    
    args = parser.parse_args()
    
    # Determine companies directory
    if args.companies_dir:
        companies_dir = Path(args.companies_dir)
    else:
        # Default to the 20251208 directory
        script_dir = Path(__file__).parent.parent
        companies_dir = script_dir.parent / "2_segment_info" / "djupanalys" / "20251208"
    
    # Determine output file
    output_file = Path(args.output) if args.output else None
    
    # Run batch generation
    await batch_generate_sites(
        companies_dir=companies_dir,
        output_metadata_file=output_file,
        use_openai_enhancement=not args.no_openai,
        use_images=not args.no_images,
        fetch_actual_costs=not args.no_actual_costs,
    )


if __name__ == "__main__":
    asyncio.run(main())
