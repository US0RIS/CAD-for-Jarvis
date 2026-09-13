from __future__ import annotations

"""Portable ForgeCAD design exchange files.

A ``.focad`` file is a ZIP container with a stable, inspectable structure intended to
be authored by ForgeCAD itself *or by an external engineering agent such as ChatGPT*.
It carries canonical project JSON, frozen purchased-component snapshots, embedded
code, every local CAD asset needed to reproduce component geometry on another
workstation, and (when exported from the desktop) the complete multi-branch design
workspace.

The extension is deliberately not ``.zip`` even though the container uses ZIP so a
ForgeCAD design can be handed around as one first-class document. Older
``.forgecad.zip`` bundles remain import-compatible.
"""
import io,json,shutil,tempfile,zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from . import component_registry as registry

FORMAT_ID="focad"
FORMAT_NAME="ForgeCAD Design"
MIME_TYPE="application/vnd.forgecad.project+zip"
BUNDLE_VERSION=1


def _asset_path(asset:dict[str,Any])->Path|None:
    rel=asset.get("relative_path")
    if rel:
        p=(registry.ASSET_DIR/str(rel)).resolve()
        try:p.relative_to(registry.ASSET_DIR.resolve())
        except ValueError:return None
        return p
    old=asset.get("path")
    if old:
        p=Path(str(old))
        return p if p.is_file() else None
    return None

def _sanitize_component(component:dict[str,Any])->dict[str,Any]:
    c=deepcopy(component)
    for asset in c.get("geometry",{}).get("assets",[]):asset.pop("path",None)
    return c

def _component_snapshots(project:dict[str,Any])->list[dict[str,Any]]:
    seen={}
    for obj in project.get("objects",[]):
        snap=obj.get("component_snapshot")
        if isinstance(snap,dict) and snap.get("id"):seen[str(snap["id"])]=_sanitize_component(snap)
    return list(seen.values())

def _projects_for_export(project:dict[str,Any],workspace:dict[str,Any]|None)->list[dict[str,Any]]:
    projects=[project]
    if isinstance(workspace,dict):
        for branch in (workspace.get("branches") or {}).values():
            if isinstance(branch,dict):projects.append(branch)
    return projects

def _sanitize_project_assets(project:dict[str,Any],assets:dict[str,Path])->dict[str,Any]:
    p=deepcopy(project)
    for obj in p.get("objects",[]):
        snap=obj.get("component_snapshot")
        if not isinstance(snap,dict):continue
        snap=_sanitize_component(snap);obj["component_snapshot"]=snap
        for asset in snap.get("geometry",{}).get("assets",[]):
            path=_asset_path(asset)
            if path and path.is_file():
                rel=str(asset.get("relative_path") or f"{asset.get('sha256','asset')[:16]}_{Path(asset.get('filename','asset.step')).name}")
                assets[rel]=path
    return p

def _sanitize_workspace(workspace:dict[str,Any],assets:dict[str,Path])->dict[str,Any]:
    result={
        "active":str(workspace.get("active") or "main"),
        "branches":{},
        "designs":deepcopy(workspace.get("designs") or {}),
    }
    for name,branch in (workspace.get("branches") or {}).items():
        if isinstance(branch,dict):result["branches"][str(name)]=_sanitize_project_assets(branch,assets)
    return result

def export_bundle_bytes(project:dict[str,Any],workspace:dict[str,Any]|None=None)->bytes:
    assets={}
    p=_sanitize_project_assets(project,assets)
    sanitized_workspace=_sanitize_workspace(workspace,assets) if isinstance(workspace,dict) else None
    snapshots={}
    for candidate in _projects_for_export(p,sanitized_workspace):
        for snap in _component_snapshots(candidate):snapshots[str(snap["id"])]=snap
    manifest={
        "format":FORMAT_ID,
        "format_name":FORMAT_NAME,
        "format_version":BUNDLE_VERSION,
        # bundle_version is retained so v1.1-era importers can still read files created
        # by newer ForgeCAD builds that otherwise remain schema-compatible.
        "bundle_version":BUNDLE_VERSION,
        "project_file":"project.json",
        "component_file":"components.json",
        "asset_count":len(assets),
        "component_count":len(snapshots),
    }
    if sanitized_workspace is not None:
        manifest["workspace_file"]="workspace.json"
        manifest["branch_count"]=len(sanitized_workspace.get("branches") or {})
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",json.dumps(manifest,indent=2));z.writestr("project.json",json.dumps(p,indent=2));z.writestr("components.json",json.dumps({"schema_version":registry.SCHEMA_VERSION,"components":list(snapshots.values())},indent=2))
        if sanitized_workspace is not None:z.writestr("workspace.json",json.dumps(sanitized_workspace,indent=2))
        for rel,path in assets.items():z.writestr("assets/"+rel.replace("\\","/"),path.read_bytes())
    return out.getvalue()

def _safe_extract(z:zipfile.ZipFile,root:Path)->None:
    root=root.resolve()
    for info in z.infolist():
        target=(root/info.filename).resolve()
        try:target.relative_to(root)
        except ValueError:raise ValueError(".focad file contains unsafe path")
    z.extractall(root)

def _validate_workspace(raw:Any)->dict[str,Any]|None:
    if raw is None:return None
    if not isinstance(raw,dict):raise ValueError(".focad workspace is malformed")
    active=str(raw.get("active") or "")
    branches=raw.get("branches")
    designs=raw.get("designs")
    if not active or not isinstance(branches,dict) or not isinstance(designs,dict):raise ValueError(".focad workspace is malformed")
    clean_branches={}
    for name,branch in branches.items():
        if not isinstance(branch,dict) or not isinstance(branch.get("objects"),list):raise ValueError(f".focad branch {name!r} is malformed")
        clean_branches[str(name)]=branch
    if active not in clean_branches:raise ValueError(".focad workspace active branch is missing")
    clean_designs={str(name):deepcopy(meta) for name,meta in designs.items() if isinstance(meta,dict)}
    return {"active":active,"branches":clean_branches,"designs":clean_designs}

def import_bundle_bytes(data:bytes)->dict[str,Any]:
    if len(data)>600*1024*1024:raise ValueError(".focad design exceeds 600 MB")
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:_safe_extract(z,root)
        except zipfile.BadZipFile as e:raise ValueError("Invalid .focad design file") from e
        manifest_path=root/"manifest.json";project_path=root/"project.json"
        if not manifest_path.is_file() or not project_path.is_file():raise ValueError(".focad requires manifest.json and project.json")
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        file_format=manifest.get("format")
        if file_format not in (None,FORMAT_ID):raise ValueError(f"Unsupported design format {file_format!r}")
        version=int(manifest.get("format_version",manifest.get("bundle_version",0)))
        if version!=BUNDLE_VERSION:raise ValueError(f"Unsupported .focad version {version}")
        project=json.loads(project_path.read_text(encoding="utf-8"))
        if not isinstance(project,dict) or not isinstance(project.get("objects"),list):raise ValueError(".focad project is malformed")
        workspace=None
        workspace_name=str(manifest.get("workspace_file") or "")
        if workspace_name:
            workspace_path=root/workspace_name
            if not workspace_path.is_file():raise ValueError(".focad manifest references a missing workspace file")
            workspace=_validate_workspace(json.loads(workspace_path.read_text(encoding="utf-8")))
        components_path=root/"components.json";installed=[]
        if components_path.is_file():
            payload=json.loads(components_path.read_text(encoding="utf-8"))
            for component in payload.get("components",[]):
                cid=str(component.get("id") or "")
                if not cid:continue
                try:registry.component_by_id(cid)
                except KeyError:
                    registry.import_components(component,replace=False,source_kind="user_supplied");installed.append(cid)
        copied=[];asset_root=root/"assets"
        if asset_root.is_dir():
            for source in asset_root.rglob("*"):
                if not source.is_file():continue
                rel=source.relative_to(asset_root);dest=(registry.ASSET_DIR/rel).resolve()
                try:dest.relative_to(registry.ASSET_DIR.resolve())
                except ValueError:raise ValueError("Unsafe component asset path in .focad file")
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);copied.append(str(rel))
        # Normalize old bundle manifests in the response. Callers can always identify an
        # imported document as a .focad-compatible design after successful validation.
        normalized={**manifest,"format":FORMAT_ID,"format_name":FORMAT_NAME,"format_version":version,"bundle_version":version}
        return {"ok":True,"project":project,"workspace":workspace,"components_installed":installed,"assets_restored":copied,"manifest":normalized}
