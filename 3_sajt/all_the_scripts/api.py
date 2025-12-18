"""
FastAPI server for generating company preview pages.
Can be used as an API endpoint for your site or standalone.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import os
from typing import Optional
import asyncio

# Import will work when run as module or via run_api.py
try:
    from .generator import generate_preview, generate_preview_v0
    from .preview_storage import (
        create_preview_entry,
        get_preview,
        cleanup_expired_previews,
        get_preview_stats,
        cleanup_task,
    )
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from generator import generate_preview, generate_preview_v0
    from preview_storage import (
        create_preview_entry,
        get_preview,
        cleanup_expired_previews,
        get_preview_stats,
        cleanup_task,
    )

app = FastAPI(
    title="Company Preview Generator API",
    description="Generate preview HTML pages for companies from folder data. Previews expire after 2 days.",
    version="2.0.0",
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Start background cleanup task on server startup."""
    asyncio.create_task(cleanup_task())
    print("✅ Preview cleanup task started (runs every 6 hours)")


class GenerateRequest(BaseModel):
    folder_name: str


@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "message": "Company Preview Generator API",
        "version": "2.0.0",
        "endpoints": {
            "GET /preview/{folder_name}": "Generate preview and return unique URL (valid 2 days)",
            "GET /p/{preview_id}": "View preview by unique ID (redirects to demoUrl)",
            "GET /preview-info/{preview_id}": "Get preview metadata",
            "GET /preview-stats": "Get statistics about stored previews",
            "GET /generate/{folder_name}": "Generate preview (alternative endpoint)",
            "POST /generate": "Generate preview (JSON body)",
            "GET /health": "Health check",
        },
        "preview_expiry_days": 2,
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/preview-stats")
async def preview_stats():
    """Get statistics about stored previews."""
    return get_preview_stats()


@app.get("/p/{preview_id}")
async def view_preview(preview_id: str):
    """
    View preview by unique ID. Redirects to demoUrl.
    Preview expires after 2 days.
    """
    entry = get_preview(preview_id)

    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Preview not found or expired. Preview ID: {preview_id}",
        )

    # Redirect to the actual demoUrl
    return RedirectResponse(url=entry["demoUrl"], status_code=302)


@app.get("/preview-info/{preview_id}")
async def preview_info(preview_id: str):
    """Get preview metadata without redirecting."""
    entry = get_preview(preview_id)

    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Preview not found or expired. Preview ID: {preview_id}",
        )

    # Return metadata (exclude demoUrl for security, or include if you want)
    return {
        "id": entry["id"],
        "company_name": entry.get("company_name"),
        "folder_name": entry.get("folder_name"),
        "created_at": entry["created_at"],
        "expires_at": entry["expires_at"],
        "accessed_count": entry.get("accessed_count", 0),
        "last_accessed": entry.get("last_accessed"),
        "preview_url": f"/p/{preview_id}",  # Relative URL to preview
        "demoUrl": entry["demoUrl"],  # Direct v0 demo URL
    }


@app.get("/generate/{folder_name}", response_class=JSONResponse)
async def generate_json(
    folder_name: str,
    use_v0: bool = Query(True, description="Use v0 API to generate React page"),
    use_openai: bool = Query(True, description="Enhance prompt with OpenAI"),
    use_images: bool = Query(True, description="Search and include stock images"),
    save: bool = Query(
        False, description="Save HTML to output folder (only for static mode)"
    ),
):
    """
    Generate preview and return JSON with demoUrl (v0) or HTML (static).

    Args:
        folder_name: Company folder name (e.g., "K928253-25")
        use_v0: Whether to use v0 API (default: True) - generates React page with demoUrl
        use_openai: Enhance prompt with OpenAI (default: True)
        use_images: Search and include stock images (default: True)
        save: Whether to save HTML file to output folder (only if use_v0=False)
    """
    try:
        if use_v0:
            # Use v0 API to generate React page
            result = await generate_preview_v0(
                folder_name, use_openai_enhancement=use_openai, use_images=use_images
            )

            # Create preview entry with unique ID
            if result.get("demoUrl"):
                preview_id = create_preview_entry(
                    demo_url=result["demoUrl"],
                    chat_id=result.get("chatId"),
                    company_name=result["company_name"],
                    folder_name=folder_name,
                    cost_info=result.get("cost"),
                )

                base_url = os.getenv("BASE_URL", "http://localhost:8000")
                result["preview_id"] = preview_id
                result["preview_url"] = f"{base_url}/p/{preview_id}"
                result["expires_in_days"] = 2

            return result
        else:
            # Fallback to static HTML generation
            result = generate_preview(folder_name)

            if save:
                # Save to output folder
                output_dir = Path(__file__).parent / "output"
                output_dir.mkdir(exist_ok=True)

                html_path = output_dir / f"{folder_name}.html"
                html_path.write_text(result["html"], encoding="utf-8")

                cost_path = output_dir / f"{folder_name}-cost.txt"
                cost_text = (
                    f"Kostnad för demo/preview: {result['cost']['formatted']}\n"
                    f"Gäller: {result['cost']['company_name']} ({result['cost']['orgnr']})\n"
                    f"Genererad: {result['cost']['generated_at']}\n"
                )
                cost_path.write_text(cost_text, encoding="utf-8")

                result["saved"] = {
                    "html_path": str(html_path),
                    "cost_path": str(cost_path),
                }

            return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@app.get("/preview/{folder_name}", response_class=JSONResponse)
async def preview_html(
    folder_name: str,
    use_v0: bool = Query(True),
    use_openai: bool = Query(True),
    use_images: bool = Query(True),
):
    """
    Generate preview and return demoUrl (v0) or redirect to HTML.

    Args:
        folder_name: Company folder name (e.g., "K928253-25")
        use_v0: Whether to use v0 API (default: True)
    """
    try:
        if use_v0:
            result = await generate_preview_v0(
                folder_name, use_openai_enhancement=use_openai, use_images=use_images
            )
            if result.get("demoUrl"):
                # Create preview entry with unique ID
                preview_id = create_preview_entry(
                    demo_url=result["demoUrl"],
                    chat_id=result.get("chatId"),
                    company_name=result["company_name"],
                    folder_name=folder_name,
                    cost_info=result.get("cost"),
                )

                # Get base URL from request
                base_url = os.getenv("BASE_URL", "http://localhost:8000")
                preview_url = f"{base_url}/p/{preview_id}"

                # Return JSON with unique preview URL
                return {
                    "success": True,
                    "preview_id": preview_id,
                    "preview_url": preview_url,  # Unique URL valid for 2 days
                    "demoUrl": result[
                        "demoUrl"
                    ],  # Direct v0 URL (for iframe if needed)
                    "chatId": result.get("chatId"),
                    "company_name": result["company_name"],
                    "cost": result["cost"],
                    "expires_in_days": 2,
                }
            else:
                raise HTTPException(
                    status_code=500, detail="v0 generation did not return demoUrl"
                )
        else:
            # Fallback: return static HTML
            result = generate_preview(folder_name)
            return HTMLResponse(content=result["html"])
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@app.post("/generate", response_class=JSONResponse)
async def generate_post(
    request: GenerateRequest,
    use_v0: bool = Query(True),
    use_openai: bool = Query(True),
    use_images: bool = Query(True),
    save: bool = Query(False),
):
    """
    Generate preview from POST request body.

    Args:
        request: JSON body with folder_name
        use_v0: Whether to use v0 API (default: True)
        use_openai: Enhance prompt with OpenAI (default: True)
        use_images: Search and include stock images (default: True)
        save: Whether to save HTML file to output folder (only if use_v0=False)
    """
    try:
        if use_v0:
            result = await generate_preview_v0(
                request.folder_name,
                use_openai_enhancement=use_openai,
                use_images=use_images,
            )

            # Create preview entry with unique ID
            if result.get("demoUrl"):
                preview_id = create_preview_entry(
                    demo_url=result["demoUrl"],
                    chat_id=result.get("chatId"),
                    company_name=result["company_name"],
                    folder_name=request.folder_name,
                    cost_info=result.get("cost"),
                )

                base_url = os.getenv("BASE_URL", "http://localhost:8000")
                result["preview_id"] = preview_id
                result["preview_url"] = f"{base_url}/p/{preview_id}"
                result["expires_in_days"] = 2

            return result
        else:
            result = generate_preview(request.folder_name)

            if save:
                output_dir = Path(__file__).parent / "output"
                output_dir.mkdir(exist_ok=True)

                html_path = output_dir / f"{request.folder_name}.html"
                html_path.write_text(result["html"], encoding="utf-8")

                cost_path = output_dir / f"{request.folder_name}-cost.txt"
                cost_text = (
                    f"Kostnad för demo/preview: {result['cost']['formatted']}\n"
                    f"Gäller: {result['cost']['company_name']} ({result['cost']['orgnr']})\n"
                    f"Genererad: {result['cost']['generated_at']}\n"
                )
                cost_path.write_text(cost_text, encoding="utf-8")

                result["saved"] = {
                    "html_path": str(html_path),
                    "cost_path": str(cost_path),
                }

            return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
