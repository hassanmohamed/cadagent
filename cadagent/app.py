"""The local demo web server: upload -> read -> confirm -> apply -> view -> download -> undo.

    uv run uvicorn cadagent.app:app --port 8000

A single-user demo that runs on a laptop: state is kept in memory and the
outputs of every version are kept under runs/. For a hosted, multi-user
version see streamlit_app.py.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import reader  # noqa: E402  (after load_dotenv so the model override is seen)
from .rules import Rules, RulesError  # noqa: E402
from .samples import SAMPLES, TEST_DATA, available_samples  # noqa: E402
from .session import NoPartYet, Session, Version, check_raw  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
RUNS = ROOT / "runs"

state = Session(RUNS)
app = FastAPI(title="AI CAD Agent POC")


@app.exception_handler(RulesError)
async def rules_error(_request, exc: RulesError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=500)


def get_rules() -> Rules:
    # Read on every request so the domain expert can edit rules.yaml while the demo runs.
    return Rules.load()


def version_payload(version: Version | None) -> dict | None:
    if version is None:
        return None
    base = f"/api/versions/{version.number}"
    return {
        "number": version.number,
        "how": version.how,
        "part": version.part.model_dump(),
        "derived": version.summary["derived"],
        "part_json": version.summary["part_json"],
        "downloads": {kind: f"{base}/files/{name}" for kind, name in version.summary["files"].items()},
        "zip_url": f"{base}/all.zip",
        "mesh_url": f"{base}/mesh",
        "flat_svg_url": f"{base}/flat.svg",
        "sheet_png_url": f"{base}/sheet.png",
    }


def state_payload() -> dict:
    rules = get_rules()
    return {
        "ai": {"available": reader.ai_available(), "model": reader.MODEL},
        "rules": rules.summary(),
        "current": version_payload(state.current),
        "history": [{"number": v.number, "name": v.part.name, "how": v.how} for v in state.versions],
        "can_undo": state.can_undo,
        "samples": available_samples(),
    }


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# --- Read ----------------------------------------------------------------------


@app.get("/api/state")
def api_state() -> dict:
    return state_payload()


@app.post("/api/read")
async def api_read(file: UploadFile = File(...), request: str = Form(""), mode: str = Form("create")):
    """Step 2: the AI reads the image. Nothing is built here."""
    if mode not in ("create", "markup"):
        return error(400, "Unknown mode.")
    data = await file.read()
    try:
        return state.read(data, file.filename or "", request, mode, get_rules())
    except NoPartYet as exc:
        return error(409, str(exc))
    except reader.ReaderError as exc:
        return error(422, str(exc))


@app.get("/api/preview")
def api_preview():
    if state.preview_png is None:
        raise HTTPException(404)
    return Response(state.preview_png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/samples/{path:path}")
def api_sample(path: str):
    if path not in {s["file"] for s in SAMPLES}:
        raise HTTPException(404)
    return FileResponse(TEST_DATA / path, headers={"Cache-Control": "no-store"})


# --- Check and build -------------------------------------------------------------


class ApplyRequest(BaseModel):
    part: dict
    how: str = "Edited by hand"
    build_anyway: bool = False


@app.post("/api/check")
def api_check(body: ApplyRequest) -> dict:
    """Check the form's values against the rules without building anything."""
    return {"issues": check_raw(body.part, get_rules())}


@app.post("/api/apply")
def api_apply(body: ApplyRequest):
    """Steps 4 and 5: check the confirmed values, then build all outputs."""
    result = state.apply(body.part, get_rules(), how=body.how, build_anyway=body.build_anyway)
    if "error" in result:
        return error(500, result["error"])
    if not result["built"]:
        return JSONResponse(result, status_code=422)
    return {**result, **state_payload()}


@app.post("/api/undo")
def api_undo():
    if not state.undo():
        return error(409, "There is no earlier version to go back to.")
    return state_payload()


@app.post("/api/reset")
def api_reset():
    state.reset()
    return state_payload()


# --- Outputs ---------------------------------------------------------------------


def _version(number: int) -> Version:
    for version in state.versions:
        if version.number == number:
            return version
    raise HTTPException(404, "That version no longer exists.")


@app.get("/api/versions/{number}/mesh")
def api_mesh(number: int):
    _version(number)
    return Response((state.version_dir(number) / "mesh.json").read_text(), media_type="application/json")


@app.get("/api/versions/{number}/flat.svg")
def api_flat_svg(number: int):
    _version(number)
    return Response((state.version_dir(number) / "flat.svg").read_text(), media_type="image/svg+xml")


@app.get("/api/versions/{number}/sheet.png")
def api_sheet_png(number: int):
    _version(number)
    return FileResponse(state.version_dir(number) / "sheet.png", media_type="image/png")


@app.get("/api/versions/{number}/all.zip")
def api_zip(number: int):
    version = _version(number)
    name = f"{Path(version.summary['files']['step']).stem}_v{len(state.versions)}.zip"
    return Response(
        state.zip_bytes(version),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/versions/{number}/files/{name}")
def api_file(number: int, name: str, download: bool = False):
    version = _version(number)
    if name not in version.summary["files"].values():
        raise HTTPException(404)
    path = state.version_dir(number) / name
    if download or not name.endswith(".pdf"):
        return FileResponse(path, filename=name)
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline", filename=name)


@app.get("/api/health")
def api_health() -> dict:
    return {"ok": True, "versions": len(state.versions)}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("cadagent.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
