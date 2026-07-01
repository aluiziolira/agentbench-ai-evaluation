import logging
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from agentbench.models import WorkflowDefinition
from agentbench.storage.mongo import ImmutableWorkflowError, WorkflowNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("")
async def register_workflow(workflow: WorkflowDefinition, req: Request) -> dict[str, str]:
    """Register a new workflow definition."""
    mongo = req.app.state.mongo

    try:
        await mongo.create_workflow(workflow)
        return {"workflow_id": workflow.workflow_id, "version": workflow.version}
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Workflow already exists") from None


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, req: Request) -> WorkflowDefinition:
    """Get latest published workflow version."""
    mongo = req.app.state.mongo

    workflow = await mongo.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    return cast(WorkflowDefinition, workflow)


@router.post("/{workflow_id}/publish")
async def publish_workflow(workflow_id: str, version: str, req: Request) -> dict[str, str]:
    """Publish a workflow version."""
    mongo = req.app.state.mongo

    try:
        await mongo.publish_workflow(workflow_id, version)
        return {"workflow_id": workflow_id, "version": version, "status": "published"}
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="Workflow not found") from None
    except ImmutableWorkflowError:
        raise HTTPException(
            status_code=409, detail="Workflow version is already published"
        ) from None
