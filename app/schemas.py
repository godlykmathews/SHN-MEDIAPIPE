from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Category = Literal['disease', 'pest', 'healthy', 'uncertain', 'not_plant']


class Finding(BaseModel):
    model_config = ConfigDict(extra='ignore')
    plant: str = Field(max_length=200)
    issue: str = Field(max_length=200)
    category: Category
    summary: str = Field(max_length=1800)
    observations: list[str] = Field(max_length=8)
    possible_causes: list[str] = Field(max_length=6)
    uncertainty: str = Field(max_length=1000)
    needs_expert: bool


class Source(BaseModel):
    title: str
    url: str


class Report(Finding):
    immediate_actions: list[str]
    treatment: list[str]
    prevention: list[str]
    sources: list[Source]


class Prediction(BaseModel):
    label: str
    score: float
    kind: str
    model: str
