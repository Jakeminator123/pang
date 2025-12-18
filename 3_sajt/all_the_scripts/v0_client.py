"""
v0 Platform API client for generating React components.
Uses v0 Platform API (not Model API) to generate React components with demo URLs.
"""

import os
import asyncio
from typing import Optional, Dict, Any
import httpx


# v0 Platform API endpoints
V0_API_BASE = "https://api.v0.dev/v1"
V0_CHATS_ENDPOINT = f"{V0_API_BASE}/chats"
V0_USAGE_ENDPOINT = f"{V0_API_BASE}/reports/usage"

# Default API key (fallback if env var not set)
DEFAULT_V0_API_KEY = os.getenv("V0_API_KEY", "")

# Supported models
SUPPORTED_MODELS = ["v0-1.5-md", "v0-1.5-lg", "v0-1.0-md"]
DEFAULT_MODEL = "v0-1.5-md"

# Timeouts
REQUEST_TIMEOUT = 300.0  # 5 minutes for generation
POLL_INTERVAL = 4  # seconds between polls
MAX_POLL_ATTEMPTS = 30  # max attempts to wait for demoUrl


class V0Client:
    """Client for v0 Platform API."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize v0 API client.

        Args:
            api_key: v0 API key (defaults to V0_API_KEY env var)
        """
        self.api_key = api_key or DEFAULT_V0_API_KEY
        if not self.api_key:
            raise ValueError("V0_API_KEY is required. Set it as environment variable or pass as parameter.")

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authorization."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def create_chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        image_generations: bool = False,
        response_mode: str = "sync",
    ) -> Dict[str, Any]:
        """
        Create a new chat and generate React component.

        Args:
            message: User prompt for the component
            system_prompt: System prompt (defaults to expert React/Next.js developer)
            model: Model to use (v0-1.5-md, v0-1.5-lg, or v0-1.0-md)
            image_generations: Whether to enable image generation
            response_mode: "sync" or "stream"

        Returns:
            Dict with chatId, demoUrl, versionId, status, files, etc.
        """
        if model not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model: {model}. Supported: {SUPPORTED_MODELS}")

        # Default system prompt for React/Next.js development
        if system_prompt is None:
            system_prompt = """You are an expert React and Next.js developer creating production-ready websites.

TECHNICAL REQUIREMENTS:
- React 18+ functional components with TypeScript
- Tailwind CSS for ALL styling (no external CSS files)
- Lucide React for icons (import from 'lucide-react')
- Next.js App Router conventions
- Responsive design (mobile-first approach)

CODE QUALITY:
- Clean, readable code with proper formatting
- Semantic HTML elements (nav, main, section, article)
- Proper TypeScript types (no 'any')
- Accessible (ARIA labels, keyboard navigation, focus states)
- SEO-friendly structure (proper heading hierarchy)

STYLING GUIDELINES:
- Use Tailwind utility classes exclusively
- Consistent spacing scale (4, 8, 12, 16, 24, 32, 48)
- CSS variables for theme colors when appropriate
- Smooth transitions: transition-all duration-300
- Proper hover/focus/active states

COMPONENT STRUCTURE:
- Single file when possible
- Extract repeated patterns into sub-components
- Props interfaces for reusable components
- Default export for main component"""

        payload = {
            "message": message,
            "system": system_prompt,
            "chatPrivacy": "private",
            "modelConfiguration": {
                "modelId": model,
                "imageGenerations": image_generations,
            },
            "responseMode": response_mode,
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            try:
                response = await client.post(
                    V0_CHATS_ENDPOINT,
                    json=payload,
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                result = response.json()

                # Extract response data
                chat_id = result.get("id")
                latest_version = result.get("latestVersion", {})
                demo_url = latest_version.get("demoUrl")
                version_id = latest_version.get("id")
                status = latest_version.get("status")

                # If demoUrl not immediately available, poll for it
                if not demo_url and status != "failed":
                    demo_url = await self._poll_for_demo_url(client, chat_id)

                return {
                    "chatId": chat_id,
                    "demoUrl": demo_url,
                    "versionId": version_id,
                    "status": status,
                    "files": latest_version.get("files", []),
                    "model": model,
                    "prompt_length": len(message),
                }

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise ValueError("Invalid V0_API_KEY - check your API key")
                elif e.response.status_code == 429:
                    raise ValueError("Rate limit exceeded - please try again later")
                raise ValueError(f"v0 API error ({e.response.status_code}): {e.response.text}")
            except httpx.TimeoutException:
                raise ValueError("Request timed out - v0 API took too long to respond")

    async def _poll_for_demo_url(
        self, client: httpx.AsyncClient, chat_id: str, max_attempts: int = MAX_POLL_ATTEMPTS
    ) -> Optional[str]:
        """
        Poll v0 API for demoUrl until ready.

        Args:
            client: HTTP client
            chat_id: Chat ID to poll
            max_attempts: Maximum number of polling attempts

        Returns:
            Demo URL if available, None otherwise
        """
        url = f"{V0_CHATS_ENDPOINT}/{chat_id}"
        headers = self._get_headers()

        for attempt in range(1, max_attempts + 1):
            await asyncio.sleep(POLL_INTERVAL)

            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                result = response.json()
                latest_version = result.get("latestVersion", {})
                status = latest_version.get("status")
                demo_url = latest_version.get("demoUrl")

                if status == "completed" and demo_url:
                    return demo_url
                elif status == "failed":
                    raise ValueError("v0 generation failed")
            except httpx.HTTPStatusError:
                continue

        return None

    async def get_chat(self, chat_id: str) -> Dict[str, Any]:
        """
        Get chat details by ID.

        Args:
            chat_id: Chat ID

        Returns:
            Chat details
        """
        url = f"{V0_CHATS_ENDPOINT}/{chat_id}"
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_usage(
        self,
        chat_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Get usage report from v0 API.

        Args:
            chat_id: Filter by specific chat ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of events to retrieve

        Returns:
            Usage report data
        """
        params = {"limit": limit}
        if chat_id:
            params["chatId"] = chat_id
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(V0_USAGE_ENDPOINT, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise ValueError("Invalid V0_API_KEY")
                raise ValueError(f"Failed to fetch usage: {e.response.text}")


# Convenience function for quick usage
async def generate_component(
    prompt: str,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Quick function to generate a React component.

    Args:
        prompt: User prompt
        api_key: v0 API key (optional)
        model: Model to use
        system_prompt: Custom system prompt (optional)

    Returns:
        Generation result with demoUrl
    """
    client = V0Client(api_key)
    return await client.create_chat(prompt, system_prompt=system_prompt, model=model)
