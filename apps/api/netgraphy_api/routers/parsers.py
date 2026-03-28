"""Parser registry and testing endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("")
async def list_parsers(
    platform: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """List registered TextFSM parser templates."""
    # TODO: Implement parser registry with platform filtering
    return {"data": [], "meta": {"total_count": 0, "page": page, "page_size": page_size}}


@router.post("", status_code=201)
async def register_parser(body: dict[str, Any]):
    """Register a new TextFSM parser template."""
    # TODO: Validate TextFSM template syntax, store in registry
    return {"data": {"id": "placeholder", **body}}


@router.get("/{parser_id}")
async def get_parser(parser_id: str):
    """Get a parser template with its metadata."""
    # TODO: Retrieve parser from registry
    raise HTTPException(status_code=404, detail=f"Parser '{parser_id}' not found")


@router.post("/{parser_id}/test")
async def test_parser(parser_id: str, body: dict[str, Any]):
    """Test a parser against raw command output.

    Body:
        raw_output: str — the raw command output to parse
    Returns parsed records.
    """
    # TODO: Load parser template, execute TextFSM against input, return results
    raw_output = body.get("raw_output", "")
    if not raw_output:
        raise HTTPException(status_code=400, detail="'raw_output' is required")
    return {"data": {"parsed_records": [], "record_count": 0}}


@router.get("/command-bundles", tags=["Command Bundles"])
async def list_command_bundles():
    """List registered command bundles."""
    # TODO: Implement command bundle registry
    return {"data": []}


@router.post("/command-bundles", status_code=201, tags=["Command Bundles"])
async def register_command_bundle(body: dict[str, Any]):
    """Register a command bundle."""
    # TODO: Validate and store command bundle
    return {"data": {"id": "placeholder", **body}}


@router.get("/mappings", tags=["Mappings"])
async def list_mappings():
    """List mapping definitions."""
    # TODO: Implement mapping registry
    return {"data": []}


@router.post("/mappings", status_code=201, tags=["Mappings"])
async def register_mapping(body: dict[str, Any]):
    """Register a mapping definition."""
    # TODO: Validate and store mapping definition
    return {"data": {"id": "placeholder", **body}}
