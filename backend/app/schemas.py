"""请求体模型。"""
from datetime import date, datetime

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class FieldUpdateIn(BaseModel):
    sensitivity_level: int | None = Field(default=None, ge=1, le=4)
    tags: list[str] | None = None
    available_from: str | None = None  # YYYY-MM-DD
    available_to: str | None = None
    is_active: bool | None = None
    semantic: str | None = None


class BatchItemIn(BaseModel):
    project_id: int
    product_id: int
    purpose_code: str


class BatchCreateIn(BaseModel):
    title: str = ""
    items: list[BatchItemIn]


class RevokeIn(BaseModel):
    reason: str = ""


class AccessQueryIn(BaseModel):
    project_id: int
    product_id: int
    purpose_code: str
    kind: str = "查询"  # 查询/导出
    requested_fields: list[str] = []
    request_id: str  # 客户端请求号：断线重试幂等
    export_rows: int = Field(default=100, ge=1)


class ReservationIn(BaseModel):
    project_id: int
    kind: str = "查询"
    note: str = ""


class UsageReportIn(BaseModel):
    project_id: int
    kind: str = "机时"  # 查询/导出/机时
    amount: float = 1
    idempotency_key: str
    note: str = ""


# ---------------- 刷新时效 ----------------

class CenterIn(BaseModel):
    code: str
    name: str
    weekday_schedule: list[int] = []  # ISO 周一=1…周日=7
    note: str = ""


class ContractIn(BaseModel):
    center_id: int
    product_id: int
    frequency: str = "每日"  # 每日/每周/每月
    expected_window_days: int = Field(default=1, ge=1, le=30)
    cutoff_time: str = "18:00"
    statistical_quantile: float = Field(default=0.9, gt=0.5, le=0.999)
    min_history_for_stat: int = Field(default=8, ge=2)


class PauseIn(BaseModel):
    center_id: int
    product_id: int | None = None  # 空 = 中心整体停诊
    pause_from: date
    pause_to: date
    reason: str = "计划停诊"


class RefreshEventIn(BaseModel):
    center_id: int
    product_id: int
    partition_date: date
    received_at: datetime
    event_kind: str = "全量刷新"  # 全量刷新/迟到补传/更正发布
    generated_at: datetime | None = None
    record_count: int = Field(default=0, ge=0)
    batch_no: str | None = None
    correction_of_id: int | None = None


class QcPassIn(BaseModel):
    validated_at: datetime
    record_count: int | None = Field(default=None, ge=0)


class QcFailIn(BaseModel):
    failed_at: datetime
    reason: str


class ReadinessIn(BaseModel):
    project_id: int
    center_id: int
    product_id: int
    analysis_cutoff: date
    window_from: date
    mode: str = "fixed"  # fixed/statistical
