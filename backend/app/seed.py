"""演示种子数据（全部为虚构输入）：产品目录、课题档案、伦理批件、成员、
额度账户、首批资格实例与一次示范访问。幂等：已有用户时跳过。"""
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .models import (
    AccessEvent, CollectionPause, DataProduct, EthicsApproval, ProductField,
    Project, ProjectMember, ProjectPurpose, QualificationBatch,
    QualificationInstance, QuotaAccount, RefreshContract, ResearchCenter, User,
)
from .security import hash_password
from .services import quota as quota_svc
from .services.compiler import compile_qualification
from .services import refresh as refresh_svc

TODAY = date.today()
D = timedelta(days=1)
_rng = random.Random(20261121)


def _product(db, code, name, source, freq, dept, desc, fields):
    p = DataProduct(
        code=code, name=name, source_system=source, update_frequency=freq,
        owner_dept=dept, description=desc,
    )
    db.add(p)
    db.flush()
    for f in fields:
        db.add(ProductField(product_id=p.id, **f))
    db.flush()
    return p


def seed(db: Session) -> None:
    # ---------------- 用户（测试账号） ----------------
    users = [
        User(username="admin", password_hash=hash_password("admin123"),
             display_name="林治理", role="ADMIN"),
        User(username="wangjianguo", password_hash=hash_password("wang123"),
             display_name="王建国", role="PI", member_name="王建国"),
        User(username="zhangmin", password_hash=hash_password("zhang123"),
             display_name="张敏", role="ANALYST", member_name="张敏"),
        User(username="zhaolei", password_hash=hash_password("zhao123"),
             display_name="赵磊", role="ANALYST", member_name="赵磊"),
        User(username="auditor", password_hash=hash_password("audit123"),
             display_name="沈审计", role="AUDITOR"),
    ]
    db.add_all(users)

    # ---------------- 产品目录 ----------------
    default_win = {"available_from": date(2020, 1, 1), "available_to": date(2027, 12, 31)}
    p_img = _product(db, "P-IMG", "影像检查数据产品", "PACS 影像系统", "每日",
                     "影像科", "胸部/腹部影像检查记录与影像组学特征", [
        {"field_name": "exam_id", "semantic": "检查编号", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "patient_name", "semantic": "患者姓名", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "patient_id_card", "semantic": "身份证号", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "modality", "semantic": "检查模态（CT/MR/DR）", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "body_part", "semantic": "检查部位", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "exam_date", "semantic": "检查日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "image_abstract", "semantic": "影像组学特征摘要（2023年中上线）",
         "data_type": "json", "sensitivity_level": 3, "tags": [],
         "available_from": date(2023, 6, 1), "available_to": date(2027, 12, 31)},
        {"field_name": "report_text", "semantic": "影像报告全文", "data_type": "text",
         "sensitivity_level": 3, "tags": [], **default_win},
    ])
    p_lab = _product(db, "P-LAB", "检验指标数据产品", "LIS 检验系统", "每日",
                     "检验科", "临床检验项目与结果指标", [
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "patient_name", "semantic": "患者姓名", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "test_item", "semantic": "检验项目名称", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "test_result", "semantic": "检验结果值", "data_type": "number",
         "sensitivity_level": 3, "tags": [],
         "available_from": date(2019, 1, 1), "available_to": date(2026, 12, 31)},
        {"field_name": "test_unit", "semantic": "计量单位", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "test_date", "semantic": "检验日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "age_at_test", "semantic": "检验时年龄", "data_type": "number",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "abnormal_flag", "semantic": "异常标记", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
    ])
    p_fu = _product(db, "P-FU", "随访记录数据产品", "随访管理平台", "每周",
                    "临床研究部", "出院后随访、生存状态与复发记录", [
        {"field_name": "followup_no", "semantic": "随访编号", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "followup_date", "semantic": "随访日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "survival_status", "semantic": "生存状态", "data_type": "string",
         "sensitivity_level": 3, "tags": [], **default_win},
        {"field_name": "recurrence_flag", "semantic": "复发标记", "data_type": "boolean",
         "sensitivity_level": 3, "tags": [], **default_win},
        {"field_name": "contact_phone", "semantic": "联系电话", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "followup_note", "semantic": "随访备注", "data_type": "text",
         "sensitivity_level": 3, "tags": [], **default_win},
    ])
    p_bio = _product(db, "P-BIO", "样本库数据产品", "样本库管理系统", "每月",
                     "生物样本库", "样本库存、质控与标志物检测", [
        {"field_name": "sample_id", "semantic": "样本编号", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "sample_type", "semantic": "样本类型（血清/组织）", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "collect_date", "semantic": "采集日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "storage_location", "semantic": "存储位置", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "gene_marker", "semantic": "基因标志物检测结果", "data_type": "json",
         "sensitivity_level": 4, "tags": ["遗传信息"], **default_win},
        {"field_name": "quality_score", "semantic": "样本质控评分", "data_type": "number",
         "sensitivity_level": 1, "tags": [], **default_win},
    ])

    # ---------------- 课题档案（用途条件 / 成员 / 伦理批件） ----------------
    prj_a = Project(code="PRJ-A", name="冠心病预后模型研究", pi_name="王建国",
                    status="在研", start_date=TODAY - 400 * D, end_date=TODAY + 500 * D)
    db.add(prj_a); db.flush()
    db.add_all([
        ProjectPurpose(project_id=prj_a.id, purpose_code="TRAIN",
                       description="预后模型训练：需要 L3 级临床与检验明细，禁止直接标识符",
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       export_allowed=True),
        ProjectPurpose(project_id=prj_a.id, purpose_code="PUBLISH",
                       description="统计结果发表：仅 L2 级汇总字段，禁止标识符与准标识符，不允许导出",
                       max_sensitivity_level=2,
                       forbidden_tags=["直接标识符", "准标识符"], export_allowed=False),
        ProjectMember(project_id=prj_a.id, name="王建国", role="PI",
                      valid_from=TODAY - 400 * D, valid_to=TODAY + 500 * D),
        ProjectMember(project_id=prj_a.id, name="张敏", role="数据分析师",
                      valid_from=TODAY - 400 * D, valid_to=TODAY + 500 * D),
        ProjectMember(project_id=prj_a.id, name="赵磊", role="统计师",
                      valid_from=TODAY - 400 * D, valid_to=TODAY + 500 * D),
        ProjectMember(project_id=prj_a.id, name="孙倩", role="研究员",
                      valid_from=TODAY - 400 * D, valid_to=TODAY - 30 * D, status="离任"),
        EthicsApproval(project_id=prj_a.id, approval_no="EA-2025-001",
                       scope_subjects="2018 年以来心内科住院冠心病患者队列",
                       allowed_purposes=["TRAIN", "PUBLISH"],
                       max_sensitivity_level=3,
                       forbidden_tags=["直接标识符", "遗传信息"],
                       valid_from=TODAY - 300 * D, valid_to=TODAY + 400 * D),
    ])

    prj_b = Project(code="PRJ-B", name="影像组学标志物探索", pi_name="陈静",
                    status="在研", start_date=TODAY - 200 * D, end_date=TODAY + 300 * D)
    db.add(prj_b); db.flush()
    db.add_all([
        ProjectPurpose(project_id=prj_b.id, purpose_code="EXTRACT",
                       description="影像特征提取：L3 级影像数据，禁止直接标识符",
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       export_allowed=True),
        ProjectMember(project_id=prj_b.id, name="陈静", role="PI",
                      valid_from=TODAY - 200 * D, valid_to=TODAY + 300 * D),
        # 张敏同时是两个课题的成员 —— 用于验证跨课题资格边界
        ProjectMember(project_id=prj_b.id, name="张敏", role="数据分析师",
                      valid_from=TODAY - 200 * D, valid_to=TODAY + 300 * D),
        EthicsApproval(project_id=prj_b.id, approval_no="EA-2025-002",
                       scope_subjects="肺结节影像回顾性队列",
                       allowed_purposes=["EXTRACT"],
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       valid_from=TODAY - 200 * D, valid_to=TODAY + 300 * D),
    ])

    prj_c = Project(code="PRJ-C", name="旧队列回顾性分析", pi_name="刘洋",
                    status="在研", start_date=TODAY - 700 * D, end_date=TODAY + 100 * D)
    db.add(prj_c); db.flush()
    db.add_all([
        ProjectPurpose(project_id=prj_c.id, purpose_code="REVIEW",
                       description="回顾性分析：L3 级历史数据",
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       export_allowed=False),
        ProjectMember(project_id=prj_c.id, name="刘洋", role="PI",
                      valid_from=TODAY - 700 * D, valid_to=TODAY + 100 * D),
        ProjectMember(project_id=prj_c.id, name="周杰", role="研究员",
                      valid_from=TODAY - 700 * D, valid_to=TODAY + 100 * D),
        # 伦理批件已过期失效 —— 用于验证批次处理中伦理失效不得签发
        EthicsApproval(project_id=prj_c.id, approval_no="EA-2024-003",
                       scope_subjects="2015-2020 年体检队列",
                       allowed_purposes=["REVIEW"],
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       valid_from=TODAY - 700 * D, valid_to=TODAY - 400 * D,
                       status="失效"),
    ])

    # ---------------- 额度账户（已批准预算 + 并发上限） ----------------
    db.add_all([
        QuotaAccount(project_id=prj_a.id, max_concurrent=3, budget_query=500,
                     budget_export_rows=20000, budget_compute_hours=100),
        QuotaAccount(project_id=prj_b.id, max_concurrent=2, budget_query=200,
                     budget_export_rows=5000, budget_compute_hours=50),
        QuotaAccount(project_id=prj_c.id, max_concurrent=1, budget_query=50,
                     budget_export_rows=1000, budget_compute_hours=10),
    ])
    db.flush()

    # ---------------- 首批资格实例（通过编译器签发，保证与求交逻辑一致） ----------------
    batch = QualificationBatch(batch_no="B-SEED-0001", title="开通前首批资格签发",
                               created_by="seed", total=0, succeeded=0, failed=0)
    db.add(batch); db.flush()
    plan = [
        (prj_a, p_lab, "TRAIN"), (prj_a, p_lab, "PUBLISH"),
        (prj_a, p_img, "TRAIN"), (prj_b, p_img, "EXTRACT"),
    ]
    for project, product, purpose_code in plan:
        compiled = compile_qualification(db, project, product, purpose_code, TODAY)
        db.add(QualificationInstance(
            batch_id=batch.id, project_id=project.id, product_id=product.id,
            purpose_code=purpose_code, status="已签发",
            field_projection=compiled.field_projection,
            covered_member_ids=compiled.covered_member_ids,
            basis=compiled.basis, catalog_version=compiled.catalog_version,
            valid_from=compiled.valid_from, valid_to=compiled.valid_to,
            issued_by="seed",
        ))
        batch.succeeded += 1
        batch.total += 1
    batch.status = "完成"
    db.flush()

    # ---------------- 一次示范访问（张敏 在 PRJ-A 用 TRAIN 查询 P-LAB） ----------------
    qual = (
        db.query(QualificationInstance)
        .filter(QualificationInstance.project_id == prj_a.id,
                QualificationInstance.product_id == p_lab.id,
                QualificationInstance.purpose_code == "TRAIN",
                QualificationInstance.status == "已签发")
        .one()
    )
    member_zm_a = db.query(ProjectMember).filter(
        ProjectMember.project_id == prj_a.id, ProjectMember.name == "张敏").one()
    request_id = "seed-demo-0001"
    reservation = quota_svc.acquire(db, prj_a.id, "查询", note="种子示范访问")
    usage, _ = quota_svc.report_usage(db, prj_a.id, "查询", 1,
                                      idempotency_key=f"access:{request_id}",
                                      note="种子示范访问消耗")
    quota_svc.release(db, reservation, status="已结算")
    granted = qual.field_projection
    event = AccessEvent(
        request_id=request_id, project_id=prj_a.id, product_id=p_lab.id,
        purpose_code="TRAIN", member_id=member_zm_a.id, member_name="张敏",
        qualification_id=qual.id, kind="查询", status="成功",
        requested_fields=[], granted_fields=granted,
        product_snapshot={
            "id": p_lab.id, "code": p_lab.code, "name": p_lab.name,
            "source_system": p_lab.source_system,
            "update_frequency": p_lab.update_frequency,
            "catalog_version": p_lab.catalog_version,
            "fields": [
                {"field_name": f.field_name, "semantic": f.semantic,
                 "data_type": f.data_type, "sensitivity_level": f.sensitivity_level,
                 "tags": f.tags, "available_from": f.available_from.isoformat(),
                 "available_to": f.available_to.isoformat(), "is_active": f.is_active}
                for f in p_lab.fields
            ],
        },
        qualification_snapshot={
            "id": qual.id, "purpose_code": qual.purpose_code, "status": qual.status,
            "valid_from": qual.valid_from.isoformat(), "valid_to": qual.valid_to.isoformat(),
            "catalog_version": qual.catalog_version,
            "field_projection": qual.field_projection,
            "covered_member_ids": qual.covered_member_ids,
            "basis": qual.basis,
        },
        quota_snapshot={
            "reservation_id": reservation.id, "usage_event_id": usage.id,
            "receipt_no": usage.receipt_no,
            "consumed": {"kind": "查询", "amount": 1},
            "balance_after": usage.balance_after, "rejected_fields": [],
        },
    )
    db.add(event); db.flush()
    reservation.access_event_id = event.id
    usage.access_event_id = event.id

    _seed_refresh(db, {"P-IMG": p_img, "P-LAB": p_lab, "P-FU": p_fu, "P-BIO": p_bio},
                  {"PRJ-A": prj_a, "PRJ-B": prj_b, "PRJ-C": prj_c})
    db.commit()


# ==================== 刷新时效演示数据（中心 / 合约 / 停诊 / 刷新事件 / 就绪快照） ====================

def _dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def _seed_refresh(db: Session, products: dict, projects: dict) -> None:
    """构造覆盖题目全部场景的虚构刷新历史：
    按日/按周/每月中心、周末停采、计划停诊、质控失败后补传、历史更正、
    迟到批次、待校验批次与长期无新批次。
    """
    # ---- 中心：排程为 ISO 周几（1=周一…7=周日），均不含周末 → 周末停采 ----
    c1 = ResearchCenter(code="RC-01", name="城东综合医学中心",
                        weekday_schedule=[1, 2, 3, 4, 5], note="工作日每日交付影像/检验分区")
    c2 = ResearchCenter(code="RC-02", name="西城专科随访中心",
                        weekday_schedule=[1, 3, 5], note="周一/三/五排程，随访产品按周交付")
    c3 = ResearchCenter(code="RC-03", name="南郊分院",
                        weekday_schedule=[1, 2, 3, 4, 5], note="近期设备老化，检验分区存在长期断更")
    db.add_all([c1, c2, c3]); db.flush()

    contracts = [
        RefreshContract(center_id=c1.id, product_id=products["P-LAB"].id, frequency="每日",
                        expected_window_days=1, cutoff_time="18:00", min_history_for_stat=8),
        RefreshContract(center_id=c1.id, product_id=products["P-IMG"].id, frequency="每日",
                        expected_window_days=1, cutoff_time="20:00", min_history_for_stat=8),
        RefreshContract(center_id=c2.id, product_id=products["P-FU"].id, frequency="每周",
                        expected_window_days=2, cutoff_time="18:00", min_history_for_stat=8),
        RefreshContract(center_id=c3.id, product_id=products["P-LAB"].id, frequency="每日",
                        expected_window_days=1, cutoff_time="18:00", min_history_for_stat=8),
        RefreshContract(center_id=c3.id, product_id=products["P-BIO"].id, frequency="每月",
                        expected_window_days=3, cutoff_time="17:00", min_history_for_stat=4),
    ]
    db.add_all(contracts); db.flush()

    # ---- 计划停诊/停采窗口：窗口内不预期采集，不算迟交 ----
    pause_start, pause_end = TODAY - 15 * D, TODAY - 13 * D
    db.add(CollectionPause(center_id=c1.id, product_id=products["P-LAB"].id,
                           pause_from=pause_start, pause_to=pause_end,
                           reason="检验流水线设备维护（计划停采）"))
    db.add(CollectionPause(center_id=c3.id, product_id=None,
                           pause_from=TODAY - 6 * D, pause_to=TODAY - 5 * D,
                           reason="中心年度院感演练（整体停诊）"))
    db.flush()

    lab_pid, img_pid, fu_pid, bio_pid = (products["P-LAB"].id, products["P-IMG"].id,
                                         products["P-FU"].id, products["P-BIO"].id)
    qc_fail_day = TODAY - 12 * D       # 质控失败 → 迟到补传
    correction_day = TODAY - 9 * D     # 历史更正
    late_day = TODAY - 6 * D           # 迟交的全量刷新
    pending_day = TODAY - 1 * D        # 已接收待校验
    pause_dates = {pause_start + i * D for i in range(3)}

    # ---- RC-01 × P-LAB：按日中心，覆盖全部典型场景 ----
    day = TODAY - 27 * D
    while day <= pending_day:
        if day.isoweekday() <= 5 and day not in pause_dates:
            if day == qc_fail_day:
                # 批次按时到达但质控失败：文件到达 ≠ 可用数据
                ev = refresh_svc.register_event(
                    db, c1.id, lab_pid, day, _dt(day + 1 * D, 9, 20),
                    generated_at=_dt(day, 21, 0), record_count=410,
                    batch_no=f"RF-LAB-{day:%Y%m%d}-V1")
                refresh_svc.fail_qc(db, ev.id, _dt(day + 1 * D, 11, 5),
                                    "检验值值域校验失败：17 条结果超出参考区间")
                # 同日的迟到补传（超过交付窗），质控通过后承担该分区水位
                bf = refresh_svc.register_event(
                    db, c1.id, lab_pid, day, _dt(day + 4 * D, 10, 0),
                    event_kind="迟到补传", generated_at=_dt(day + 4 * D, 8, 30),
                    record_count=398, batch_no=f"RF-LAB-{day:%Y%m%d}-BF")
                refresh_svc.pass_qc(db, bf.id, _dt(day + 4 * D, 11, 30), record_count=398)
            elif day == correction_day:
                # 首次发布正常；后续批次发布更正（不是全量刷新），更正延迟单独统计
                ev = refresh_svc.register_event(
                    db, c1.id, lab_pid, day, _dt(day + 1 * D, 8, 40),
                    record_count=522, batch_no=f"RF-LAB-{day:%Y%m%d}-V1")
                refresh_svc.pass_qc(db, ev.id, _dt(day + 1 * D, 10, 0), record_count=522)
                corr = refresh_svc.register_event(
                    db, c1.id, lab_pid, day, _dt(day + 6 * D, 15, 0),
                    event_kind="更正发布", generated_at=_dt(day + 6 * D, 14, 0),
                    record_count=526, correction_of_id=ev.id,
                    batch_no=f"RF-LAB-{day:%Y%m%d}-V2")
                refresh_svc.pass_qc(db, corr.id, _dt(day + 6 * D, 16, 20), record_count=526)
            elif day == late_day:
                # 迟交 3 天的全量刷新
                ev = refresh_svc.register_event(
                    db, c1.id, lab_pid, day, _dt(day + 3 * D, 9, 10),
                    generated_at=_dt(day + 3 * D, 7, 50),
                    record_count=_rng.randint(300, 700),
                    batch_no=f"RF-LAB-{day:%Y%m%d}-V1")
                refresh_svc.pass_qc(db, ev.id, _dt(day + 3 * D, 10, 30))
            elif day == pending_day:
                # 已接收、质控未完成 → 就绪判定应为「待校验」
                refresh_svc.register_event(
                    db, c1.id, lab_pid, day, _dt(TODAY, 8, 30),
                    generated_at=_dt(day, 22, 0), record_count=0,
                    batch_no=f"RF-LAB-{day:%Y%m%d}-V1")
            else:
                ev = refresh_svc.register_event(
                    db, c1.id, lab_pid, day,
                    _dt(day + 1 * D, _rng.randint(8, 15), _rng.randint(0, 50)),
                    generated_at=_dt(day, 21, 30),
                    record_count=_rng.randint(300, 900),
                    batch_no=f"RF-LAB-{day:%Y%m%d}-V1")
                refresh_svc.pass_qc(db, ev.id, _dt(day + 1 * D, 17, 0))
        day += 1 * D

    # ---- RC-01 × P-IMG：按日影像分区，整体及时，最近一批待校验 ----
    day = TODAY - 12 * D
    while day <= TODAY - 1 * D:
        if day.isoweekday() <= 5:
            if day == TODAY - 1 * D:
                refresh_svc.register_event(
                    db, c1.id, img_pid, day, _dt(TODAY, 7, 50),
                    generated_at=_dt(day, 23, 10), batch_no=f"RF-IMG-{day:%Y%m%d}-V1")
            else:
                ev = refresh_svc.register_event(
                    db, c1.id, img_pid, day, _dt(day + 1 * D, 9, 0),
                    record_count=_rng.randint(120, 360),
                    batch_no=f"RF-IMG-{day:%Y%m%d}-V1")
                refresh_svc.pass_qc(db, ev.id, _dt(day + 1 * D, 18, 0))
        day += 1 * D

    # ---- RC-02 × P-FU：按周中心，每周一一个分区，8 周历史，含 1 次迟交 ----
    monday = TODAY - TODAY.isoweekday() * D + 1 * D  # 本周一
    weekly_partitions = [monday - i * 7 * D for i in range(8)][::-1]
    for idx, wday in enumerate(weekly_partitions):
        if idx == 5:  # 一次迟交
            ev = refresh_svc.register_event(
                db, c2.id, fu_pid, wday, _dt(wday + 5 * D, 14, 0),
                record_count=_rng.randint(60, 140), batch_no=f"RF-FU-{wday:%Y%m%d}-V1")
            refresh_svc.pass_qc(db, ev.id, _dt(wday + 5 * D, 16, 0))
        else:
            ev = refresh_svc.register_event(
                db, c2.id, fu_pid, wday, _dt(wday + 1 * D, 10, 0),
                record_count=_rng.randint(60, 140), batch_no=f"RF-FU-{wday:%Y%m%d}-V1")
            refresh_svc.pass_qc(db, ev.id, _dt(wday + 1 * D, 15, 0))

    # ---- RC-03 × P-LAB：长期无新批次（TODAY-10 后断更） ----
    day = TODAY - 24 * D
    while day <= TODAY - 10 * D:
        if day.isoweekday() <= 5:
            ev = refresh_svc.register_event(
                db, c3.id, lab_pid, day, _dt(day + 1 * D, 10, 0),
                record_count=_rng.randint(200, 500), batch_no=f"RF-LAB3-{day:%Y%m%d}-V1")
            refresh_svc.pass_qc(db, ev.id, _dt(day + 1 * D, 16, 0))
        day += 1 * D
    # ---- RC-03 × P-BIO：每月分区（每月 1 日），最近 4 个月 ----
    for back in range(4, 0, -1):
        m = TODAY.replace(day=1)
        for _ in range(back):
            m = (m.replace(day=1) - 1 * D).replace(day=1)
        ev = refresh_svc.register_event(
            db, c3.id, bio_pid, m, _dt(m + 2 * D, 9, 30),
            record_count=_rng.randint(80, 200), batch_no=f"RF-BIO-{m:%Y%m}-V1")
        refresh_svc.pass_qc(db, ev.id, _dt(m + 2 * D, 14, 0))

    db.flush()

    # ---- 两条示范就绪判定快照（冻结水位与证据；新批次只标记 superseded，不覆盖） ----
    refresh_svc.evaluate_readiness(
        db, projects["PRJ-A"].id, c1.id, lab_pid,
        analysis_cutoff=TODAY - 3 * D, window_from=TODAY - 24 * D,
        mode="fixed", created_by="seed")
    refresh_svc.evaluate_readiness(
        db, projects["PRJ-B"].id, c2.id, fu_pid,
        analysis_cutoff=TODAY - 2 * D, window_from=weekly_partitions[0],
        mode="statistical", created_by="seed")
    db.flush()
