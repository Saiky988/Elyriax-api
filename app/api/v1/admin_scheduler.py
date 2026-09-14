from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from app.core.deps import verify_admin
from app.services.scheduler.genshin_scheduler import run_genshin_auto_checkin

router = APIRouter(dependencies=[Depends(verify_admin)])

@router.post("/test-checkin")
async def test_checkin(background_tasks: BackgroundTasks):
    try:
        background_tasks.add_task(run_genshin_auto_checkin)
        return {"success": True, "message": "testing"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})
