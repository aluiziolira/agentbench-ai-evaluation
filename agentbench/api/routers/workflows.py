"""Workflow API endpoints."""

from fastapi import APIRouter, HTTPException, Request

from agentbench.models import WorkflowDefinition

router = APIRouter()


@router.post("")
async def register_workflow(workflow: WorkflowDefinition, req: Request):
    """Register a new workflow definition."""
    mongo = req.app.state.mongo

    try:
        await mongo.create_workflow(workflow)
        return {"workflow_id": workflow.workflow_id, "version": workflow.version}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, req: Request):
    """Get latest published workflow version."""
    mongo = req.app.state.mongo

    workflow = await mongo.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    return workflow


@router.post("/{workflow_id}/publish")
async def publish_workflow(workflow_id: str, version: str, req: Request):
    """Publish a workflow version."""
    mongo = req.app.state.mongo

    try:
        await mongo.publish_workflow(workflow_id, version)
        return {"workflow_id": workflow_id, "version": version, "status": "published"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
