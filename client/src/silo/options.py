from pydantic import BaseModel, ConfigDict


class Options(BaseModel):
    """Fields every package has. A recipe adds its own by subclassing."""

    model_config = ConfigDict(extra="forbid")

    shared: bool = False
