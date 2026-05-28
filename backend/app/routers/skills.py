from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_skill_registry
from packages.schema.models import SkillSpec
from packages.skills.registry import SkillRegistry

router = APIRouter()
SkillRegistryDep = Annotated[SkillRegistry, Depends(get_skill_registry)]


@router.get("/skills", response_model=list[SkillSpec])
def list_skills(registry: SkillRegistryDep) -> list[SkillSpec]:
    return registry.list()
