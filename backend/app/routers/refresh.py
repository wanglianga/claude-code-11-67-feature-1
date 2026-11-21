"""刷新时效路由：中心/合约/停诊维护、刷新事件登记与质控、时效画像、就绪判定与复算。

权限约定与其余路由一致：基础数据与事件登记限 ADMIN；画像查询与就绪评估对全部登录角色开放。
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    CollectionPause, DataProduct, ReadinessSnapshot, RefreshContract,
    RefreshEvent, ResearchCenter, User,
)
from ..schemas import (
    CenterIn, ContractIn, PauseIn, QcFailIn, QcPassIn, ReadinessIn,
    RefreshEventIn,
)
from ..security import current_user, require_roles
from ..serializers import (
    center_dict, contract_dict, pause_dict, readiness_dict, refresh_event_dict,
)
from ..services import refresh as svc
from ..services.refresh import RefreshError

router = APIRouter(prefix="/api/refresh", tags=["刷新时效"])


def _parse_date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


# ----------------------------- 研究中心 -----------------------------

@router.get("/centers")
def list_centers(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.query(ResearchCenter).order_by(ResearchCenter.id).all()
    return [center_dict(c) for c in rows]


@router.post("/centers")
def create_center(payload: CenterIn, db: Session = Depends(get_db),
                  _: User = Depends(require_roles("ADMIN"))):
    if db.query(ResearchCenter).filter(ResearchCenter.code == payload.code).first():
        raise HTTPException(409, f"中心编码 {payload.code} 已存在")
    if payload.weekday_schedule and not all(1 <= d <= 7 for d in payload.weekday_schedule):
        raise HTTPException(400, "weekday_schedule 取值必须在 1-7（ISO 周一=1…周日=7）")
    center = ResearchCenter(**payload.model_dump())
    db.add(center)
    db.commit()
    return center_dict(center)


# ----------------------------- 刷新合约 -----------------------------

@router.get("/contracts")
def list_contracts(center_id: int | None = None, product_id: int | None = None,
                   db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(RefreshContract).order_by(RefreshContract.id)
    if center_id:
        q = q.filter(RefreshContract.center_id == center_id)
    if product_id:
        q = q.filter(RefreshContract.product_id == product_id)
    return [contract_dict(c) for c in q.all()]


@router.post("/contracts")
def create_contract(payload: ContractIn, db: Session = Depends(get_db),
                    _: User = Depends(require_roles("ADMIN"))):
    if db.get(ResearchCenter, payload.center_id) is None:
        raise HTTPException(404, "研究中心不存在")
    if db.get(DataProduct, payload.product_id) is None:
        raise HTTPException(404, "数据产品不存在")
    if payload.frequency not in ("每日", "每周", "每月"):
        raise HTTPException(400, "frequency 仅支持 每日/每周/每月")
    exists = db.query(RefreshContract).filter(
        RefreshContract.center_id == payload.center_id,
        RefreshContract.product_id == payload.product_id).first()
    if exists:
        raise HTTPException(409, "该中心-产品分区的刷新合约已存在")
    try:
        hh, mm = payload.cutoff_time.split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "cutoff_time 格式应为 HH:MM")
    contract = RefreshContract(**payload.model_dump())
    db.add(contract)
    db.commit()
    return contract_dict(contract)


# ----------------------------- 计划停诊 -----------------------------

@router.get("/pauses")
def list_pauses(center_id: int | None = None, db: Session = Depends(get_db),
                _: User = Depends(current_user)):
    q = db.query(CollectionPause).order_by(CollectionPause.id.desc())
    if center_id:
        q = q.filter(CollectionPause.center_id == center_id)
    return [pause_dict(p) for p in q.limit(200).all()]


@router.post("/pauses")
def create_pause(payload: PauseIn, db: Session = Depends(get_db),
                 _: User = Depends(require_roles("ADMIN"))):
    if db.get(ResearchCenter, payload.center_id) is None:
        raise HTTPException(404, "研究中心不存在")
    if payload.pause_to < payload.pause_from:
        raise HTTPException(400, "停诊结束日不能早于开始日")
    pause = CollectionPause(**payload.model_dump())
    db.add(pause)
    db.commit()
    return pause_dict(pause)


# ----------------------------- 刷新事件 -----------------------------

@router.get("/events")
def list_events(center_id: int | None = None, product_id: int | None = None,
                partition_from: str | None = None, partition_to: str | None = None,
                db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(RefreshEvent).order_by(
        RefreshEvent.partition_date.desc(), RefreshEvent.id.desc())
    if center_id:
        q = q.filter(RefreshEvent.center_id == center_id)
    if product_id:
        q = q.filter(RefreshEvent.product_id == product_id)
    pf, pt = _parse_date(partition_from), _parse_date(partition_to)
    if pf:
        q = q.filter(RefreshEvent.partition_date >= pf)
    if pt:
        q = q.filter(RefreshEvent.partition_date <= pt)
    return [refresh_event_dict(e) for e in q.limit(300).all()]


@router.post("/events")
def register_event(payload: RefreshEventIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("ADMIN"))):
    """登记批次接收。新批次只使涉及分区/研究截止范围的旧就绪快照标记 superseded（内容不覆盖）。"""
    try:
        event = svc.register_event(
            db, payload.center_id, payload.product_id, payload.partition_date,
            payload.received_at, event_kind=payload.event_kind,
            generated_at=payload.generated_at, record_count=payload.record_count,
            batch_no=payload.batch_no, correction_of_id=payload.correction_of_id,
        )
        affected = svc.mark_superseded(db, payload.center_id, payload.product_id,
                                       payload.partition_date)
    except RefreshError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"event": refresh_event_dict(event), "snapshots_marked_superseded": affected}


@router.post("/events/{event_id}/qc-pass")
def qc_pass(event_id: int, payload: QcPassIn, db: Session = Depends(get_db),
            _: User = Depends(require_roles("ADMIN"))):
    """质控通过：批次成为可用数据并进入水位；引用该分区的旧快照标记 superseded。"""
    try:
        event = svc.pass_qc(db, event_id, payload.validated_at, payload.record_count)
        affected = svc.mark_superseded(db, event.center_id, event.product_id,
                                       event.partition_date)
    except RefreshError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"event": refresh_event_dict(event), "snapshots_marked_superseded": affected}


@router.post("/events/{event_id}/qc-fail")
def qc_fail(event_id: int, payload: QcFailIn, db: Session = Depends(get_db),
            _: User = Depends(require_roles("ADMIN"))):
    """质控失败：文件到达但不可用，不进入水位，失败原因留痕。"""
    try:
        event = svc.fail_qc(db, event_id, payload.failed_at, payload.reason)
        affected = svc.mark_superseded(db, event.center_id, event.product_id,
                                       event.partition_date)
    except RefreshError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"event": refresh_event_dict(event), "snapshots_marked_superseded": affected}


# ----------------------------- 时效画像 -----------------------------

@router.get("/profiles")
def get_profile(center_id: int, product_id: int,
                window_from: str | None = None, window_to: str | None = None,
                db: Session = Depends(get_db), _: User = Depends(current_user)):
    try:
        return svc.build_profile(db, center_id, product_id,
                                 _parse_date(window_from), _parse_date(window_to))
    except RefreshError as exc:
        raise HTTPException(404, str(exc))


# ----------------------------- 就绪判定 -----------------------------

@router.post("/readiness")
def evaluate(payload: ReadinessIn, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    if payload.window_from > payload.analysis_cutoff:
        raise HTTPException(400, "window_from 不能晚于 analysis_cutoff")
    try:
        snapshot = svc.evaluate_readiness(
            db, payload.project_id, payload.center_id, payload.product_id,
            payload.analysis_cutoff, payload.window_from, mode=payload.mode,
            created_by=user.username,
        )
    except RefreshError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return readiness_dict(snapshot)


@router.get("/readiness")
def list_readiness(project_id: int | None = None, center_id: int | None = None,
                   product_id: int | None = None, db: Session = Depends(get_db),
                   _: User = Depends(current_user)):
    q = db.query(ReadinessSnapshot).order_by(ReadinessSnapshot.id.desc())
    if project_id:
        q = q.filter(ReadinessSnapshot.project_id == project_id)
    if center_id:
        q = q.filter(ReadinessSnapshot.center_id == center_id)
    if product_id:
        q = q.filter(ReadinessSnapshot.product_id == product_id)
    return [readiness_dict(s) for s in q.limit(100).all()]


@router.get("/readiness/{snapshot_id}")
def readiness_detail(snapshot_id: int, db: Session = Depends(get_db),
                     _: User = Depends(current_user)):
    snap = db.get(ReadinessSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(404, "就绪快照不存在")
    return readiness_dict(snap)


@router.post("/readiness/{snapshot_id}/recompute")
def recompute(snapshot_id: int, db: Session = Depends(get_db),
              _: User = Depends(current_user)):
    """由刷新事件与合约排程重新复算，对照历史冻结结论（复算不落新快照）。"""
    try:
        return svc.recompute_snapshot(db, snapshot_id)
    except RefreshError as exc:
        raise HTTPException(404, str(exc))
