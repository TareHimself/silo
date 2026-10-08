import semver
from typing import Union, Optional, Annotated, Any
from pydantic import (
    BaseModel,
    GetCoreSchemaHandler,
)
from pydantic_core import core_schema


# Tell Pydantic how to handle semver.Version
class _SemverAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ):
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @staticmethod
    def _validate(v: Any) -> semver.Version:
        if isinstance(v, semver.Version):
            return v
        if isinstance(v, str):
            return semver.Version.parse(v, optional_minor_and_patch=True)
        raise ValueError(f"Cannot parse {v!r} as a semver version")


SemverVersion = Annotated[semver.Version, _SemverAnnotation]


class Dependency(BaseModel):
    name: str
    version: Optional[SemverVersion] = None
    options: Optional[dict[str, Union[str, bool, int]]] = None

    @staticmethod
    def from_str(
        dependency: str, options: Optional[dict[str, Union[str, bool, int]]] = None
    ) -> "Dependency":
        parts = dependency.split("@")
        name = parts[0]
        version = (
            semver.Version.parse(parts[1], optional_minor_and_patch=True)
            if len(parts) > 1
            else None
        )
        return Dependency(name=name, version=version, options=options)
