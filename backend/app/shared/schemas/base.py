"""
app/shared/schemas/base.py
Base Pydantic schema for the application.
"""

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """
    Base schema for all Pydantic models.
    Enforces common configurations.
    """
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )
