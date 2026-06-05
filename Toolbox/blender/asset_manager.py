"""
toolbox/blender/asset_manager.py

Asset library manager for Hayeong's 3D creations.
Organizes Blender outputs into a queryable folder structure under
Logs/outputs/blender/assets/.

Functions:
    register_asset(name, asset_type, blend_path, script_path, metadata)
    register_variant(parent_asset_id, variant_name, variant_type, blend_path, ...)
    get_asset(asset_id)
    list_assets(asset_type, james_approved)
    update_asset_notes(asset_id, ...)
    promote_session_output(session_file_path, name, asset_type, ...)
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from brain.config import BLENDER_OUTPUT

_ASSETS_ROOT = Path(BLENDER_OUTPUT) / "assets"
_INDEX_FILE  = _ASSETS_ROOT / "asset_index.json"

_TYPE_FOLDERS = {
    "character":   "characters",
    "prop":        "props",
    "environment": "environments",
    "shape":       "shapes",
}


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    return re.sub(r"\W+", "_", name.lower()).strip("_")


def _make_asset_id(asset_type: str, name: str) -> str:
    return f"{asset_type}_{_normalize_name(name)}_base"


def _load_index() -> dict:
    try:
        if _INDEX_FILE.exists():
            return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"last_updated": "", "total_assets": 0, "assets": []}


def _save_index(index: dict) -> None:
    _ASSETS_ROOT.mkdir(parents=True, exist_ok=True)
    index["last_updated"] = datetime.now().isoformat()
    index["total_assets"] = len(index["assets"])
    _INDEX_FILE.write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _get_asset_dir(asset_id: str) -> "Path | None":
    """Return the asset directory from the index entry, or None if not found."""
    index = _load_index()
    entry = next((a for a in index["assets"] if a["asset_id"] == asset_id), None)
    if not entry:
        return None
    # path stored as "assets/characters/elara/" — strip "assets/" to get relative to _ASSETS_ROOT
    rel = entry["path"].removeprefix("assets/").rstrip("/")
    return _ASSETS_ROOT / rel


def _load_manifest(asset_dir: Path) -> dict:
    manifests = list(asset_dir.glob("*_manifest.json"))
    if not manifests:
        return {}
    try:
        return json.loads(manifests[0].read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(asset_dir: Path, manifest: dict) -> None:
    folder_name = asset_dir.name
    manifest["last_modified"] = datetime.now().isoformat()
    path = asset_dir / f"{folder_name}_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _copy_file(src: str, dest: Path) -> bool:
    """Copy src to dest. Returns True on success."""
    try:
        src_path = Path(src)
        if src_path.exists():
            shutil.copy2(src_path, dest)
            return True
    except Exception as e:
        print(f"[asset_manager] File copy failed: {e}")
    return False


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def register_asset(
    name: str,
    asset_type: str,
    blend_path: str,
    script_path: str = None,
    metadata: dict = None,
) -> str:
    """
    Register a new base asset. Creates folder structure, copies files,
    writes manifest, updates index. Returns the asset_id.
    asset_type: "character" | "prop" | "environment" | "shape"
    """
    if asset_type not in _TYPE_FOLDERS:
        raise ValueError(
            f"Unknown asset_type '{asset_type}'. Valid: {list(_TYPE_FOLDERS)}"
        )

    asset_id    = _make_asset_id(asset_type, name)
    folder_name = _normalize_name(name)
    asset_dir   = _ASSETS_ROOT / _TYPE_FOLDERS[asset_type] / folder_name
    exports_dir = asset_dir / "exports"
    variants_dir = asset_dir / "variants"

    for d in (asset_dir, exports_dir, variants_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Copy output file into asset directory
    blend_src  = Path(blend_path) if blend_path else None
    base_file  = ""
    if blend_src and blend_src.exists():
        dest = asset_dir / f"base{blend_src.suffix}"
        _copy_file(str(blend_src), dest)
        base_file = dest.name
        # Also keep a copy in exports/
        _copy_file(str(blend_src), exports_dir / blend_src.name)

    # Copy script
    if script_path and Path(script_path).exists():
        _copy_file(script_path, asset_dir / "base_script.py")

    # Write manifest
    meta = metadata or {}
    manifest = {
        "asset_id":      asset_id,
        "name":          name,
        "type":          asset_type,
        "category":      _TYPE_FOLDERS[asset_type],
        "created_at":    datetime.now().isoformat(),
        "last_modified": datetime.now().isoformat(),
        "status":        "pending",
        "quality_rating": None,
        "james_approved": False,
        "hayeong_notes":  "",
        "james_notes":    "",
        "base_blend":     base_file,
        "base_script":    "base_script.py" if script_path else "",
        "poly_count":     None,
        "has_materials":  False,
        "has_rig":        False,
        "has_uv":         False,
        "variants":       [],
        "exports":        [blend_src.name] if (blend_src and blend_src.exists()) else [],
        "story_context":  meta.get("story_context", ""),
        "description":    meta.get("description", ""),
        "tags":           meta.get("tags", []),
    }
    _save_manifest(asset_dir, manifest)

    # Update index
    index = _load_index()
    index["assets"] = [a for a in index["assets"] if a["asset_id"] != asset_id]
    index["assets"].append({
        "asset_id":      asset_id,
        "name":          name,
        "type":          asset_type,
        "path":          f"assets/{_TYPE_FOLDERS[asset_type]}/{folder_name}/",
        "status":        "pending",
        "james_approved": False,
        "variant_count":  0,
    })
    _save_index(index)

    print(f"[asset_manager] Registered: {asset_id} → {asset_dir}")
    return asset_id


def register_variant(
    parent_asset_id: str,
    variant_name: str,
    variant_type: str,
    blend_path: str,
    script_path: str = None,
    description: str = "",
    changes: list = None,
) -> str:
    """
    Register a variant of an existing asset.
    Returns the variant_id.
    """
    asset_dir = _get_asset_dir(parent_asset_id)
    if not asset_dir or not asset_dir.exists():
        raise ValueError(f"Parent asset '{parent_asset_id}' not found.")

    variant_id   = parent_asset_id.replace("_base", f"_{_normalize_name(variant_name)}")
    v_folder     = _normalize_name(variant_name)
    variant_dir  = asset_dir / "variants" / v_folder
    variant_dir.mkdir(parents=True, exist_ok=True)

    # Copy output file
    blend_src = Path(blend_path) if blend_path else None
    v_file    = ""
    if blend_src and blend_src.exists():
        dest   = variant_dir / f"{v_folder}{blend_src.suffix}"
        _copy_file(str(blend_src), dest)
        v_file = dest.name

    # Copy script
    if script_path and Path(script_path).exists():
        _copy_file(script_path, variant_dir / f"{v_folder}_script.py")

    # Write variant manifest
    v_manifest = {
        "variant_id":        variant_id,
        "parent_asset_id":   parent_asset_id,
        "name":              variant_name,
        "variant_type":      variant_type,
        "created_at":        datetime.now().isoformat(),
        "description":       description,
        "blend_file":        v_file,
        "script_file":       f"{v_folder}_script.py" if script_path else "",
        "export_files":      [v_file] if v_file else [],
        "james_approved":    False,
        "hayeong_notes":     "",
        "changes_from_base": changes or [],
    }
    manifest_path = variant_dir / f"{v_folder}_manifest.json"
    manifest_path.write_text(
        json.dumps(v_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Update parent manifest's variants list
    parent_manifest = _load_manifest(asset_dir)
    if parent_manifest:
        variants = parent_manifest.get("variants", [])
        if variant_id not in variants:
            variants.append(variant_id)
        parent_manifest["variants"] = variants
        _save_manifest(asset_dir, parent_manifest)

    # Update index variant count
    index = _load_index()
    for entry in index["assets"]:
        if entry["asset_id"] == parent_asset_id:
            entry["variant_count"] = entry.get("variant_count", 0) + 1
            break
    _save_index(index)

    return variant_id


def get_asset(asset_id: str) -> dict:
    """Read and return an asset manifest by ID."""
    asset_dir = _get_asset_dir(asset_id)
    if not asset_dir:
        return {}
    return _load_manifest(asset_dir)


def list_assets(asset_type: str = None, james_approved: bool = None) -> list:
    """
    Return list of asset index entries.
    Optionally filter by type or approval status.
    """
    index = _load_index()
    results = index.get("assets", [])
    if asset_type:
        results = [a for a in results if a["type"] == asset_type]
    if james_approved is not None:
        results = [a for a in results if a["james_approved"] == james_approved]
    return results


def update_asset_notes(
    asset_id: str,
    hayeong_notes: str = None,
    james_notes: str = None,
    james_approved: bool = None,
    quality_rating: "int | None" = None,
) -> bool:
    """
    Update notes and approval status on an asset manifest.
    Hayeong calls this to record her assessment; James calls it for approvals.
    """
    asset_dir = _get_asset_dir(asset_id)
    if not asset_dir:
        print(f"[asset_manager] Asset '{asset_id}' not found.")
        return False

    manifest = _load_manifest(asset_dir)
    if not manifest:
        return False

    if hayeong_notes is not None:
        manifest["hayeong_notes"] = hayeong_notes
    if james_notes is not None:
        manifest["james_notes"] = james_notes
    if james_approved is not None:
        manifest["james_approved"] = james_approved
        manifest["status"] = "approved" if james_approved else manifest["status"]
    if quality_rating is not None:
        manifest["quality_rating"] = quality_rating

    _save_manifest(asset_dir, manifest)

    # Sync james_approved back to index
    if james_approved is not None:
        index = _load_index()
        for entry in index["assets"]:
            if entry["asset_id"] == asset_id:
                entry["james_approved"] = james_approved
                entry["status"] = manifest["status"]
                break
        _save_index(index)

    return True


def promote_session_output(
    session_file_path: str,
    name: str,
    asset_type: str,
    script_path: str = None,
    metadata: dict = None,
) -> str:
    """
    Promote a raw session output to the asset library.
    Copies the file, creates folder structure, registers the asset.
    Returns asset_id.
    """
    return register_asset(
        name=name,
        asset_type=asset_type,
        blend_path=session_file_path,
        script_path=script_path,
        metadata=metadata,
    )
