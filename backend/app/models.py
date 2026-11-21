"""数据模型：产品目录、课题档案、资格实例、额度账本、访问事件与审计快照。"""
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# 敏感等级：1 公开 / 2 内部 / 3 敏感 / 4 高度敏感（直接标识、遗传信息等）
SENSITIVITY_LABELS = {1: "L1 公开", 2: "L2 内部", 3: "L3 敏感", 4: "L4 高度敏感"}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(256))
    display_name: Mapped[str] = mapped_column(sa.String(64))
    # ADMIN 数据治理管理员 / PI 课题负责人 / ANALYST 数据分析师 / AUDITOR 审计员
    role: Mapped[str] = mapped_column(sa.String(16))
    # 分析师/PI 登录后在各课题中对应的成员姓名（成员记录按课题分别建档）
    member_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class DataProduct(Base):
    __tablename__ = "data_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    source_system: Mapped[str] = mapped_column(sa.String(64))   # 来源系统：PACS/LIS/随访平台/样本库
    update_frequency: Mapped[str] = mapped_column(sa.String(32))  # 更新频率：每日/每周/每月
    owner_dept: Mapped[str] = mapped_column(sa.String(64), default="")
    description: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="上架")  # 上架/下架
    catalog_version: Mapped[int] = mapped_column(sa.Integer, default=1)  # 目录版本，字段变更即递增
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    fields: Mapped[list["ProductField"]] = relationship(
        back_populates="product", order_by="ProductField.id", cascade="all, delete-orphan"
    )


class ProductField(Base):
    __tablename__ = "product_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    field_name: Mapped[str] = mapped_column(sa.String(64))
    semantic: Mapped[str] = mapped_column(sa.String(256))       # 字段语义（业务含义）
    data_type: Mapped[str] = mapped_column(sa.String(32), default="string")
    sensitivity_level: Mapped[int] = mapped_column(sa.Integer)  # 1-4
    tags: Mapped[list] = mapped_column(JSONB, default=list)     # 直接标识符/准标识符/遗传信息 等
    available_from: Mapped[date] = mapped_column(sa.Date)       # 可用时间范围起
    available_to: Mapped[date] = mapped_column(sa.Date)         # 可用时间范围止
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    product: Mapped[DataProduct] = relationship(back_populates="fields")


class CatalogChangeLog(Base):
    """目录变更日志：字段/产品每次修改留痕，供审计对比"当时定义"。"""

    __tablename__ = "catalog_change_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    change_type: Mapped[str] = mapped_column(sa.String(32))  # 新增字段/修改字段/停用字段/更新产品
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    actor: Mapped[str] = mapped_column(sa.String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    pi_name: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(16), default="在研")  # 在研/结题/暂停
    start_date: Mapped[date] = mapped_column(sa.Date)
    end_date: Mapped[date] = mapped_column(sa.Date)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    purposes: Mapped[list["ProjectPurpose"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectPurpose.id"
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectMember.id"
    )
    ethics: Mapped[list["EthicsApproval"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="EthicsApproval.id"
    )


class ProjectPurpose(Base):
    """课题申报的研究目的及其用途条件（字段放行的约束之一）。"""

    __tablename__ = "project_purposes"
    __table_args__ = (sa.UniqueConstraint("project_id", "purpose_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    purpose_code: Mapped[str] = mapped_column(sa.String(32))
    description: Mapped[str] = mapped_column(sa.String(256))
    max_sensitivity_level: Mapped[int] = mapped_column(sa.Integer, default=2)
    forbidden_tags: Mapped[list] = mapped_column(JSONB, default=list)
    export_allowed: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="purposes")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (sa.UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    role: Mapped[str] = mapped_column(sa.String(32))  # PI/数据分析师/研究员/统计师
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_to: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.String(16), default="在职")  # 在职/离任

    project: Mapped[Project] = relationship(back_populates="members")


class EthicsApproval(Base):
    """伦理批件：适用对象、允许用途、敏感等级上限与有效期。"""

    __tablename__ = "ethics_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    approval_no: Mapped[str] = mapped_column(sa.String(64), unique=True)
    scope_subjects: Mapped[str] = mapped_column(sa.String(256))  # 适用对象
    allowed_purposes: Mapped[list] = mapped_column(JSONB, default=list)  # 用途编码列表，["*"] 表示全部
    max_sensitivity_level: Mapped[int] = mapped_column(sa.Integer, default=3)
    forbidden_tags: Mapped[list] = mapped_column(JSONB, default=list)
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_to: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.String(16), default="有效")  # 有效/失效/暂停
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="ethics")


class QualificationBatch(Base):
    """资格开通批次：一次开通申请的处理结果，逐项独立状态，绝不整体假报成功。"""

    __tablename__ = "qualification_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(sa.String(128), default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="处理中")  # 完成/部分完成/失败
    total: Mapped[int] = mapped_column(sa.Integer, default=0)
    succeeded: Mapped[int] = mapped_column(sa.Integer, default=0)
    failed: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_by: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)

    items: Mapped[list["QualificationInstance"]] = relationship(back_populates="batch")


class QualificationInstance(Base):
    """资格实例：按（项目 × 产品 × 用途）隔离的字段投影与有效期。

    设计选择：采用独立资格实例模式（每个项目-产品-用途一条记录），
    审计直观、撤回传播范围明确；同一三元组同一时刻至多一条"已签发"。
    """

    __tablename__ = "qualification_instances"
    __table_args__ = (
        sa.Index(
            "uq_active_qualification",
            "project_id", "product_id", "purpose_code",
            unique=True,
            postgresql_where=sa.text("status = '已签发'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(sa.ForeignKey("qualification_batches.id"), nullable=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    purpose_code: Mapped[str] = mapped_column(sa.String(32))
    status: Mapped[str] = mapped_column(sa.String(16), default="已签发")  # 已签发/签发失败/已撤回
    fail_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    # 字段投影：编译时求交后的可用人字段及各自有效窗口（快照，签发后不再随目录变化）
    field_projection: Mapped[list] = mapped_column(JSONB, default=list)
    covered_member_ids: Mapped[list] = mapped_column(JSONB, default=list)  # 签发时在职成员范围
    # 资格依据：伦理批件快照、用途条件、成员范围、被剔除字段及原因
    basis: Mapped[dict] = mapped_column(JSONB, default=dict)
    catalog_version: Mapped[int] = mapped_column(sa.Integer, default=1)  # 签发依据的目录版本
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_to: Mapped[date] = mapped_column(sa.Date)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    issued_by: Mapped[str] = mapped_column(sa.String(64), default="system")
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    batch: Mapped[QualificationBatch | None] = relationship(back_populates="items")
    product: Mapped[DataProduct] = relationship()
    project: Mapped[Project] = relationship()


class QuotaAccount(Base):
    """额度账户：已批准预算 + 实际消耗 + 并发占用上限（按课题建账）。"""

    __tablename__ = "quota_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), unique=True, index=True)
    max_concurrent: Mapped[int] = mapped_column(sa.Integer, default=3)      # 并发占用上限
    budget_query: Mapped[int] = mapped_column(sa.Integer, default=0)        # 已批准查询次数
    used_query: Mapped[int] = mapped_column(sa.Integer, default=0)
    budget_export_rows: Mapped[int] = mapped_column(sa.Integer, default=0)  # 已批准导出行数
    used_export_rows: Mapped[int] = mapped_column(sa.Integer, default=0)
    budget_compute_hours: Mapped[float] = mapped_column(sa.Float, default=0)  # 已批准机时
    used_compute_hours: Mapped[float] = mapped_column(sa.Float, default=0)

    project: Mapped[Project] = relationship()


class QuotaReservation(Base):
    """并发占用记录：查询/导出执行期间占用一个并发槽。"""

    __tablename__ = "quota_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("quota_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))  # 查询/导出
    status: Mapped[str] = mapped_column(sa.String(16), default="占用中")  # 占用中/已结算/已释放
    access_event_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    released_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)


class UsageEvent(Base):
    """用量事件：一次实际消耗。idempotency_key 全局唯一，重复上报只扣一次。"""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("quota_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))  # 查询/导出/机时
    amount: Mapped[float] = mapped_column(sa.Float, default=1)
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    receipt_no: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)
    access_event_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    balance_after: Mapped[dict] = mapped_column(JSONB, default=dict)  # 扣减后的账户快照
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    reports: Mapped[list["UsageReport"]] = relationship(back_populates="event", order_by="UsageReport.id")


class UsageReport(Base):
    """用量上报记录：每次上报（含断线重试的重复上报）都留痕，重复回执可查。"""

    __tablename__ = "usage_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("usage_events.id"), index=True)
    is_duplicate: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    reported_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    event: Mapped[UsageEvent] = relationship(back_populates="reports")


class AccessEvent(Base):
    """数据访问事件：携带当时的产品定义、资格依据与额度变化快照，供审计还原。"""

    __tablename__ = "access_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)  # 客户端请求号，重试幂等
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    purpose_code: Mapped[str] = mapped_column(sa.String(32))
    member_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    member_name: Mapped[str] = mapped_column(sa.String(64))
    qualification_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    kind: Mapped[str] = mapped_column(sa.String(16), default="查询")  # 查询/导出
    status: Mapped[str] = mapped_column(sa.String(16))  # 成功/拒绝
    deny_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    requested_fields: Mapped[list] = mapped_column(JSONB, default=list)
    granted_fields: Mapped[list] = mapped_column(JSONB, default=list)
    product_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)       # 当时的产品定义
    qualification_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)  # 当时的资格依据
    quota_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)          # 当时的额度变化
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


# ==================== 数据产品刷新时效：中心 / 合约 / 停诊 / 刷新事件 / 就绪快照 ====================

# 刷新事件状态：已接收（质控未完成）/ 已校验（可用）/ 校验失败（不可用）/ 已更正（旧批次被后续批次更正）
REFRESH_EVENT_STATUSES = ("已接收", "已校验", "校验失败", "已更正")
# 事件性质：全量刷新 / 迟到补传 / 更正发布（更正不是全量刷新）
REFRESH_KINDS = ("全量刷新", "迟到补传", "更正发布")
# 就绪判定状态：及时 / 延迟 / 缺失 / 待校验 / 预期无采集
READINESS_STATES = ("及时", "延迟", "缺失", "待校验", "预期无采集")
# 判定模式：固定期限（按目录约定）/ 统计阈值（按历史到达分布）
READINESS_MODES = ("fixed", "statistical")


class ResearchCenter(Base):
    """研究中心：数据产品按中心分区交付，刷新时效画像按（中心 × 产品）建立。"""

    __tablename__ = "research_centers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    # 周内排程（ISO 周一=1 … 周日=7）：按日中心通常为 1-5，按周中心为指定工作日
    weekday_schedule: Mapped[list] = mapped_column(JSONB, default=list)
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class RefreshContract(Base):
    """刷新合约（目录约定）：（中心 × 产品）分区的预期交付窗与固定期限阈值。

    expected_window_days：分区数据日之后多少个自然日内应交付（固定期限判定的逾期阈值）。
    cutoff_time：交付窗截止时刻（HH:MM），与 expected_window_days 共同确定 expected_due_at。
    statistical_quantile：统计阈值模式使用的历史分位（如 0.9）。
    min_history_for_stat：统计模式要求的最少历史已校验批次，不足时回退固定期限并说明原因。
    """

    __tablename__ = "refresh_contracts"
    __table_args__ = (sa.UniqueConstraint("center_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    center_id: Mapped[int] = mapped_column(sa.ForeignKey("research_centers.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    frequency: Mapped[str] = mapped_column(sa.String(16))  # 每日/每周/每月
    expected_window_days: Mapped[int] = mapped_column(sa.Integer, default=1)
    cutoff_time: Mapped[str] = mapped_column(sa.String(8), default="18:00")
    statistical_quantile: Mapped[float] = mapped_column(sa.Float, default=0.9)
    min_history_for_stat: Mapped[int] = mapped_column(sa.Integer, default=8)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    center: Mapped[ResearchCenter] = relationship()
    product: Mapped[DataProduct] = relationship()


class CollectionPause(Base):
    """计划停诊/停采窗口：窗口内分区不预期采集，缺批次标记「预期无采集」而非迟交。"""

    __tablename__ = "collection_pauses"

    id: Mapped[int] = mapped_column(primary_key=True)
    center_id: Mapped[int] = mapped_column(sa.ForeignKey("research_centers.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("data_products.id"), nullable=True, index=True)  # null = 中心整体停诊
    pause_from: Mapped[date] = mapped_column(sa.Date, index=True)
    pause_to: Mapped[date] = mapped_column(sa.Date)
    reason: Mapped[str] = mapped_column(sa.String(256), default="")  # 计划停诊/设备维护/节假日安排
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class RefreshEvent(Base):
    """刷新事件：中心-产品分区一次批次的生成/接收/校验全过程记录。

    关键区分：
    - event_kind=更正发布 表示对旧分区的修订，不是全量刷新；correction_of_id 指向被更正的旧事件；
    - 校验未通过（status=校验失败）只代表文件到达，不计入可用水位；
    - 迟到补传（event_kind=迟到补传）是历史分区的补交付，首次发布延迟与更正延迟分别统计。
    可用批次（is_available）= 已校验 或 已更正（被更正事件保留首次发布事实，水位由替代批次承担）。
    """

    __tablename__ = "refresh_events"
    __table_args__ = (
        sa.UniqueConstraint("center_id", "product_id", "partition_date", "event_kind",
                            "correction_of_id", name="uq_refresh_partition_attempt"),
        sa.Index("ix_refresh_lookup", "center_id", "product_id", "partition_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    center_id: Mapped[int] = mapped_column(sa.ForeignKey("research_centers.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    partition_date: Mapped[date] = mapped_column(sa.Date, index=True)  # 批次对应的数据日（周/月产品为周期起始日）
    batch_no: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)
    event_kind: Mapped[str] = mapped_column(sa.String(16), default="全量刷新")  # 全量刷新/迟到补传/更正发布
    status: Mapped[str] = mapped_column(sa.String(16), default="已接收")
    generated_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)  # 批次生成时间
    received_at: Mapped[datetime] = mapped_column(sa.DateTime)   # 批次接收时间（文件到达）
    validated_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)  # 质控通过时间
    qc_failed_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    record_count: Mapped[int] = mapped_column(sa.Integer, default=0)  # 批次记录数（水位佐证，系统不补造数据）
    revision_no: Mapped[int] = mapped_column(sa.Integer, default=1)  # 1=首次发布，>1=修订版次
    correction_of_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("refresh_events.id"), nullable=True)
    # 预期交付截止（由合约与排程在登记时计算落库，作为固定期限判定与复算依据）
    expected_due_at: Mapped[datetime] = mapped_column(sa.DateTime)
    # 画像度量落库（登记/QC/更正时计算），便于直接复算与审计
    first_publish_delay_hours: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    correction_delay_hours: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    center: Mapped[ResearchCenter] = relationship()
    product: Mapped[DataProduct] = relationship()
    correction_of: Mapped["RefreshEvent | None"] = relationship(remote_side="RefreshEvent.id")


class ReadinessSnapshot(Base):
    """就绪判定快照：评估时把所引用的水位与全部依据冻结，后续新批次不改变历史判断。

    新增批次只重算涉及的（中心/产品分区、研究截止范围）；旧快照保留其 watermark_snapshot，
    审计时可凭引用的事件 id 列表由刷新事件重新复算。
    """

    __tablename__ = "readiness_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    center_id: Mapped[int] = mapped_column(sa.ForeignKey("research_centers.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    analysis_cutoff: Mapped[date] = mapped_column(sa.Date, index=True)  # 分析截止日
    window_from: Mapped[date] = mapped_column(sa.Date)                  # 研究时间窗起
    mode: Mapped[str] = mapped_column(sa.String(16))                    # fixed/statistical
    state: Mapped[str] = mapped_column(sa.String(16))                   # 及时/延迟/缺失/待校验/预期无采集
    reason: Mapped[str] = mapped_column(sa.String(512), default="")
    # 冻结的实际水位与证据（实际水位而非只有红黄状态）
    watermark_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 复算依据：参与判定的刷新事件 id、阈值版本、画像分位数等
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    superseded: Mapped[bool] = mapped_column(sa.Boolean, default=False)  # 涉及分区出现新批次后标记（旧记录仍保留）
    created_by: Mapped[str] = mapped_column(sa.String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
