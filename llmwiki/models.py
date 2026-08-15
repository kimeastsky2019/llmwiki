"""정적 분석 결과 데이터 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class JavaMethod:
    name: str
    return_type: str = ""
    params: list[list[str]] = field(default_factory=list)  # [[type, name], ...]
    annotations: list[str] = field(default_factory=list)
    url_mappings: list[str] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0
    calls: list[list[str]] = field(default_factory=list)  # [[receiver, method], ...]
    sql_refs: list[str] = field(default_factory=list)  # "namespace.id" 직접 호출
    body: str = ""


@dataclass
class JavaClass:
    path: str
    package: str
    name: str
    kind: str = "unknown"  # controller|service|serviceimpl|dao|mapper|vo|util|unknown
    is_interface: bool = False
    annotations: list[str] = field(default_factory=list)
    extends: str | None = None
    implements: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    fields: list[list[str]] = field(default_factory=list)  # [[type, name], ...]
    methods: list[JavaMethod] = field(default_factory=list)
    class_mapping: str = ""  # 클래스 레벨 @RequestMapping
    source: str = ""

    @property
    def fqn(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name


@dataclass
class SqlStatement:
    id: str
    namespace: str
    kind: str  # select|insert|update|delete
    sql: str
    tables: list[str] = field(default_factory=list)
    crud: list[list[str]] = field(default_factory=list)  # [[table, "C"|"R"|"U"|"D"], ...]
    params: list[str] = field(default_factory=list)
    parameter_type: str | None = None
    result_type: str | None = None
    path: str = ""
    line: int = 0

    @property
    def full_id(self) -> str:
        return f"{self.namespace}.{self.id}"


@dataclass
class MapperXml:
    path: str
    namespace: str
    statements: list[SqlStatement] = field(default_factory=list)


@dataclass
class Program:
    """MD 산출물 1건에 대응하는 논리 단위 (보통 Controller 1개)."""

    id: str  # 파일/URL 안전한 슬러그
    name: str  # 화면/업무명
    layer: str  # 기관계/채널계/공통 …
    tier: str  # frontend|backend
    entry_fqn: str  # 진입 클래스 FQN
    classes: list[str] = field(default_factory=list)  # 관련 클래스 FQN
    mappers: list[str] = field(default_factory=list)  # mapper namespace
    sql_ids: list[str] = field(default_factory=list)  # namespace.id
    tables: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    service_ids: list[str] = field(default_factory=list)  # 메서드 단위 서비스 ID
    files: list[str] = field(default_factory=list)  # 원본 소스 경로


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj
