from pydantic import BaseModel, Field

class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled creation", max_length=180)
    kind: str = Field(default="video", pattern="^(video|audio)$")
    script: str = Field(default="", max_length=20000)

class ProjectOut(BaseModel):
    id: int
    title: str
    kind: str
    status: str
    script: str
    media_path: str | None
    created_at: str
