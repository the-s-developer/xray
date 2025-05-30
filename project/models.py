from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Prompt(BaseModel):
    role: str
    content: str

class Project(BaseModel):
    projectId: str
    projectName: str
    projectDescription: Optional[str] = ""
    projectStatus: Optional[str] = "active"
    scraperDomain: Optional[str] = ""
    createdAt: str
    updatedAt: str
    prompts: List[Prompt] = []
    executionConfig: Optional[Dict[str, Any]] = {}

class ScriptVersion(BaseModel):
    scriptId: str
    projectId: str
    version: int
    code: str
    createdAt: str
    generatedByLLM: Optional[bool] = False
    notes: Optional[str] = ""
    class Config:
        extra = "ignore"


class Execution(BaseModel):
    executionId: str
    projectId: str
    scriptId: str
    scriptVersion: int
    status: str
    startTime: str
    endTime: Optional[str] = None
    duration: Optional[int] = 0
    resultCount: Optional[int] = 0
    output: Optional[str] = ""
    errorMessage: Optional[str] = ""
    result: Optional[dict] = {}
