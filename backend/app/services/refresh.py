"""刷新时效服务：刷新事件登记/质控/更正、时效画像计算与就绪判定。

领域规则（与题目一一对应）：
- 合约给出预期交付窗；按中心周内排程推算每个分区的预期交付截止 expected_due_at。
- 计划停诊窗口内的分区不预期采集 → 就绪状态为「预期无采集」，不算迟交。
- 刷新事件区分 全量刷新 / 迟到补传 / 更正发布：
  * 首次发布延迟 = 首次批次接收时间 - 预期截止；
  * 更正延迟 = 更正批次接收时间 - 被更正批次的接收时间（与首次发布延迟分别统计）；
  * 更正发布不是全量刷新，不改变分区的首次发布事实。
- 质控未通过（校验失败）的批次只代表文件到达，不进入可用水位；
  待质控（已接收）对应就绪状态「待校验」。
- 画像：实际延迟分位数、连续未更新区间、迟到补传比例、按研究时间窗的数据水位。
- 判定模式：
  * fixed 固定期限：按合约 expected_window_days 判定逾期，直观可追责；
  * statistical 统计阈值：由历史「已校验首次发布」批次的到达延迟分布给条件时效区间，
    历史批次不足 min_history_for_stat 时回退固定期限并在依据中说明。
- 就绪评估冻结水位与证据到 ReadinessSnapshot；新批次只重算涉及分区与截止范围，
  旧快照保留所引用水位（superseded 仅作标记，不覆盖快照内容）。
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from ..models import (
    CollectionPause, DataProduct, Project, ReadinessSnapshot, RefreshContract,
    RefreshEvent, ResearchCenter,
)

AVAILABLE_STATUSES = ("已校验", "已更正")
PENDING_STATUSES = ("已接收",)
FAILED_STATUSES = ("校验失败",)


class RefreshError(Exception):
    """刷新时效业务校验失败。"""


# ----------------------------- 基础工具 -----------------------------

def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") if len(value) > 10 \
        else datetime.strptime(value, "%Y-%m-%d")


def _cutoff_dt(day: date, cutoff_time: str) -> datetime:
    hh, mm = cutoff_time.split(":")
    return datetime.combine(day, time(int(hh), int(mm)))


def quantile(values: list[float], q: float) -> float | None:
    """线性插值分位数（与 numpy 默认方法一致），空序列返回 None。"""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return round(xs[0], 2)
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    frac = pos - lo
    if lo + 1 >= len(xs):
        return round(xs[-1], 2)
    return round(xs[lo] * (1 - frac) + xs[lo + 1] * frac, 2)


def scheduled_dow(center: ResearchCenter, contract: RefreshContract) -> list[int]:
    """生效的周内排程：中心排程为空时按合约频率给默认值。"""
    if center.weekday_schedule:
        return list(center.weekday_schedule)
    if contract.frequency == "每周":
        return [1]
    if contract.frequency == "每月":
        return [1]
    return [1, 2, 3, 4, 5]


def expected_due_for_partition(
    center: ResearchCenter, contract: RefreshContract, partition: date
) -> datetime:
    """按合约与中心排程推算分区的预期交付截止时刻。

    每日：分区日 + expected_window_days 个自然日的 cutoff_time；
    每周/每月：从分区日（周期起始日）起，找第 expected_window_days 个排程工作日的 cutoff_time。
    """
    dows = scheduled_dow(center, contract)
    if contract.frequency == "每日":
        due_day = partition + timedelta(days=contract.expected_window_days)
        return _cutoff_dt(due_day, contract.cutoff_time)

    due_day = partition
    found = 0
    guard = 0
    while found < contract.expected_window_days and guard < 60:
        due_day += timedelta(days=1)
        if due_day.isoweekday() in dows:
            found += 1
        guard += 1
    if found < contract.expected_window_days:
        # 排程异常稀疏时退化为自然日，保证仍可判定
        due_day = partition + timedelta(days=contract.expected_window_days)
    return _cutoff_dt(due_day, contract.cutoff_time)


def is_paused(db: Session, center_id: int, product_id: int, day: date) -> CollectionPause | None:
    """该分区日落入中心整体停诊或该产品停采窗口则返回停诊记录。"""
    rows = (
        db.query(CollectionPause)
        .filter(CollectionPause.center_id == center_id,
                CollectionPause.pause_from <= day,
                CollectionPause.pause_to >= day)
        .all()
    )
    for row in rows:
        if row.product_id is None or row.product_id == product_id:
            return row
    return None


# ----------------------------- 事件登记 / 质控 / 更正 -----------------------------

def _get_contract(db: Session, center_id: int, product_id: int) -> RefreshContract:
    contract = (
        db.query(RefreshContract)
        .filter(RefreshContract.center_id == center_id,
                RefreshContract.product_id == product_id,
                RefreshContract.active.is_(True))
        .first()
    )
    if contract is None:
        raise RefreshError("该中心-产品分区不存在生效中的刷新合约")
    return contract


def register_event(
    db: Session,
    center_id: int,
    product_id: int,
    partition_date: date,
    received_at: datetime,
    event_kind: str = "全量刷新",
    generated_at: datetime | None = None,
    record_count: int = 0,
    batch_no: str | None = None,
    correction_of_id: int | None = None,
) -> RefreshEvent:
    """登记一次批次到达（文件接收）。此时质控未必完成，状态为「已接收」。

    迟到补传/更正发布必须指向同一分区已有的历史批次；更正发布须指定被更正事件。
    """
    center = db.get(ResearchCenter, center_id)
    if center is None:
        raise RefreshError("研究中心不存在")
    if db.get(DataProduct, product_id) is None:
        raise RefreshError("数据产品不存在")
    contract = _get_contract(db, center_id, product_id)

    if event_kind not in ("全量刷新", "迟到补传", "更正发布"):
        raise RefreshError("event_kind 仅支持 全量刷新/迟到补传/更正发布")

    prior = (
        db.query(RefreshEvent)
        .filter(RefreshEvent.center_id == center_id,
                RefreshEvent.product_id == product_id,
                RefreshEvent.partition_date == partition_date)
        .order_by(RefreshEvent.id)
        .all()
    )
    if event_kind == "全量刷新" and prior:
        raise RefreshError("该分区已有批次，补交付请登记为「迟到补传」，修订请登记为「更正发布」")
    if event_kind in ("迟到补传", "更正发布") and not prior:
        raise RefreshError(f"{event_kind}必须指向同分区已存在的历史批次")
    if event_kind == "更正发布" and correction_of_id is None:
        raise RefreshError("更正发布必须指定被更正的刷新事件 correction_of_id")

    correction_of = None
    if correction_of_id is not None:
        correction_of = db.get(RefreshEvent, correction_of_id)
        if correction_of is None or correction_of.center_id != center_id \
                or correction_of.product_id != product_id \
                or correction_of.partition_date != partition_date:
            raise RefreshError("被更正事件不存在或不属于同一中心-产品-分区")
        if correction_of.status not in AVAILABLE_STATUSES:
            raise RefreshError("只能更正已校验可用的历史批次（失败批次应补传而非更正）")

    due_at = expected_due_for_partition(center, contract, partition_date)
    first_delay = round((received_at - due_at).total_seconds() / 3600.0, 2)
    correction_delay = None
    revision_no = 1
    if correction_of is not None:
        correction_delay = round((received_at - correction_of.received_at).total_seconds() / 3600.0, 2)
        revision_no = (correction_of.revision_no or 1) + 1

    event = RefreshEvent(
        center_id=center_id, product_id=product_id, partition_date=partition_date,
        batch_no=batch_no or ("RF" + uuid.uuid4().hex[:14].upper()),
        event_kind=event_kind, status="已接收",
        generated_at=generated_at, received_at=received_at,
        record_count=record_count, revision_no=revision_no,
        correction_of_id=correction_of_id,
        expected_due_at=due_at,
        first_publish_delay_hours=first_delay,
        correction_delay_hours=correction_delay,
    )
    db.add(event)
    db.flush()
    return event


def pass_qc(db: Session, event_id: int, validated_at: datetime,
            record_count: int | None = None) -> RefreshEvent:
    """质控通过：批次成为可用数据。迟到补传通过后，同分区失败的旧批次标记「已更正」语义由替代关系保留；
    更正发布通过后，被更正批次置为「已更正」，水位由新批次承担。"""
    event = db.get(RefreshEvent, event_id)
    if event is None:
        raise RefreshError("刷新事件不存在")
    if event.status not in ("已接收", "校验失败"):
        raise RefreshError(f"当前状态「{event.status}」不能再做质控通过")
    event.status = "已校验"
    event.validated_at = validated_at
    event.qc_failed_at = None
    event.fail_reason = None
    if record_count is not None:
        event.record_count = record_count
    db.flush()

    if event.event_kind == "更正发布" and event.correction_of_id:
        old = db.get(RefreshEvent, event.correction_of_id)
        if old is not None and old.status == "已校验":
            old.status = "已更正"
            db.flush()
    return event


def fail_qc(db: Session, event_id: int, failed_at: datetime, reason: str) -> RefreshEvent:
    """质控失败：文件到达但不可用，不进入可用水位，失败原因留痕。"""
    event = db.get(RefreshEvent, event_id)
    if event is None:
        raise RefreshError("刷新事件不存在")
    if event.status not in ("已接收",):
        raise RefreshError(f"当前状态「{event.status}」不能登记质控失败")
    event.status = "校验失败"
    event.qc_failed_at = failed_at
    event.fail_reason = reason or "质控未通过"
    db.flush()
    return event


# ----------------------------- 画像计算 -----------------------------

def _first_publish_events(events: list[RefreshEvent]) -> list[RefreshEvent]:
    """每个分区的首次发布批次。

    只统计曾经可用（已校验/已更正）的批次——质控失败、仅到达未校验的批次不构成发布；
    更正发布虽可用，但它是修订而非首次发布，取最早的非更正可用批次。
    """
    by_partition: dict[date, RefreshEvent] = {}
    for e in events:
        if e.status not in AVAILABLE_STATUSES or e.event_kind == "更正发布":
            continue
        cur = by_partition.get(e.partition_date)
        if cur is None or e.received_at < cur.received_at:
            by_partition[e.partition_date] = e
    return list(by_partition.values())


def _available_event_for_partition(events: list[RefreshEvent]) -> RefreshEvent | None:
    """分区当前承担可用水位的批次：可用事件中版次最高（最新修订），否则 None。"""
    usable = [e for e in events if e.status in AVAILABLE_STATUSES]
    if not usable:
        return None
    return sorted(usable, key=lambda e: (e.revision_no, e.received_at))[-1]


def iter_expected_partitions(
    center: ResearchCenter, contract: RefreshContract,
    window_from: date, window_to: date,
) -> list[date]:
    """按合约频率枚举研究窗内的预期分区锚点日。

    每日：每个排程工作日；每周：每个 ISO 周在排程最小工作日（通常周一）一个锚点；
    每月：每月 1 日一个锚点（交付截止仍按排程工作日推算）。
    """
    dows = set(scheduled_dow(center, contract))
    days: list[date] = []
    if contract.frequency == "每日":
        day = window_from
        while day <= window_to:
            if day.isoweekday() in dows:
                days.append(day)
            day += timedelta(days=1)
        return days

    if contract.frequency == "每周":
        anchor_dow = min(dows)
        day = window_from - timedelta(days=window_from.isoweekday() - anchor_dow)
        if day < window_from:
            day += timedelta(days=7)
        while day <= window_to:
            days.append(day)
            day += timedelta(days=7)
        return days

    # 每月：每月 1 日
    day = window_from.replace(day=1)
    while day <= window_to:
        days.append(day)
        if day.month == 12:
            day = day.replace(year=day.year + 1, month=1)
        else:
            day = day.replace(month=day.month + 1)
    return days


def build_profile(db: Session, center_id: int, product_id: int,
                  window_from: date | None = None, window_to: date | None = None) -> dict:
    """计算（中心 × 产品）分区的刷新时效画像。"""
    center = db.get(ResearchCenter, center_id)
    contract = (
        db.query(RefreshContract)
        .filter(RefreshContract.center_id == center_id,
                RefreshContract.product_id == product_id,
                RefreshContract.active.is_(True))
        .first()
    )
    if center is None or contract is None:
        raise RefreshError("中心或刷新合约不存在")

    q = db.query(RefreshEvent).filter(
        RefreshEvent.center_id == center_id,
        RefreshEvent.product_id == product_id,
    )
    if window_from:
        q = q.filter(RefreshEvent.partition_date >= window_from)
    if window_to:
        q = q.filter(RefreshEvent.partition_date <= window_to)
    events = q.order_by(RefreshEvent.partition_date, RefreshEvent.id).all()

    firsts = _first_publish_events(events)
    delays = [e.first_publish_delay_hours for e in firsts
              if e.first_publish_delay_hours is not None]
    late_firsts = [e for e in firsts if (e.first_publish_delay_hours or 0) > 0]
    on_time_firsts = [e for e in firsts if (e.first_publish_delay_hours or 0) <= 0]

    # 迟到补传比例：首次发布靠迟到补传完成的分区 / 有首次发布的分区
    backfill_partitions = {e.partition_date for e in firsts if e.event_kind == "迟到补传"}
    backfill_ratio = round(len(backfill_partitions) / len(firsts), 4) if firsts else 0.0

    # 更正延迟（与首次发布延迟分离统计）
    corrections = [e for e in events if e.event_kind == "更正发布"]
    correction_delays = [e.correction_delay_hours for e in corrections
                         if e.correction_delay_hours is not None]

    # 连续未更新区间：按排程日扫描窗口内分区，找最长的「无可用批次」连续段
    gaps = _coverage_gaps(db, center, contract, events, window_from, window_to)
    longest_gap = max(gaps, key=lambda g: g["days"], default=None)

    # 统计模式阈值：历史已校验首次发布批次的到达延迟分位（条件时效区间）
    qualified_firsts = [e for e in firsts if e.status in AVAILABLE_STATUSES]
    stat_delays = [e.first_publish_delay_hours for e in qualified_firsts
                   if e.first_publish_delay_hours is not None]
    stat_ready_hours = quantile(stat_delays, contract.statistical_quantile)

    failed = [e for e in events if e.status == "校验失败"]
    pending = [e for e in events if e.status == "已接收"]

    return {
        "center_id": center_id,
        "center_code": center.code,
        "center_name": center.name,
        "product_id": product_id,
        "product_code": contract.product.code,
        "product_name": contract.product.name,
        "frequency": contract.frequency,
        "expected_window_days": contract.expected_window_days,
        "cutoff_time": contract.cutoff_time,
        "weekday_schedule": scheduled_dow(center, contract),
        "window_from": window_from.isoformat() if window_from else None,
        "window_to": window_to.isoformat() if window_to else None,
        "total_events": len(events),
        "partition_count": len({e.partition_date for e in events}),
        "first_publish_count": len(firsts),
        "on_time_count": len(on_time_firsts),
        "late_count": len(late_firsts),
        "backfill_partition_count": len(backfill_partitions),
        "backfill_ratio": backfill_ratio,
        "correction_count": len(corrections),
        "qc_failed_count": len(failed),
        "pending_qc_count": len(pending),
        "delay_hours": {
            "min": round(min(delays), 2) if delays else None,
            "p50": quantile(delays, 0.5),
            "p90": quantile(delays, 0.9),
            "max": round(max(delays), 2) if delays else None,
            "mean": round(sum(delays) / len(delays), 2) if delays else None,
        },
        "correction_delay_hours": {
            "p50": quantile(correction_delays, 0.5),
            "p90": quantile(correction_delays, 0.9),
            "max": round(max(correction_delays), 2) if correction_delays else None,
        },
        "statistical": {
            "quantile": contract.statistical_quantile,
            "ready_threshold_hours": stat_ready_hours,
            "history_size": len(stat_delays),
            "min_history_required": contract.min_history_for_stat,
            "usable": len(stat_delays) >= contract.min_history_for_stat,
        },
        "longest_gap": longest_gap,
        "gaps": gaps,
    }


def _coverage_gaps(db: Session, center: ResearchCenter, contract: RefreshContract,
                   events: list[RefreshEvent],
                   window_from: date | None, window_to: date | None) -> list[dict]:
    """扫描预期分区，列出无可用批次的连续区间（停诊窗口单独标注，不计入迟交缺口）。"""
    if not window_from or not window_to:
        return []
    available_map: dict[date, RefreshEvent] = {}
    grouped: dict[date, list[RefreshEvent]] = {}
    for e in events:
        grouped.setdefault(e.partition_date, []).append(e)
    for d, evs in grouped.items():
        winner = _available_event_for_partition(evs)
        if winner is not None:
            available_map[d] = winner

    gaps: list[dict] = []
    gap_start: date | None = None
    gap_days = 0
    for day in iter_expected_partitions(center, contract, window_from, window_to):
        pause = is_paused(db, center.id, contract.product_id, day)
        missing = pause is None and day not in available_map
        if missing:
            if gap_start is None:
                gap_start = day
            gap_days += 1
        else:
            # 停诊日与可用分区都会终止连续缺分段；停诊日本身不属于缺失，不计入缺口天数
            if gap_start is not None:
                gaps.append({"from": gap_start.isoformat(),
                             "to": (day - timedelta(days=1)).isoformat(),
                             "days": gap_days, "paused_days": 0})
                gap_start, gap_days = None, 0
    if gap_start is not None:
        gaps.append({"from": gap_start.isoformat(),
                     "to": window_to.isoformat(), "days": gap_days,
                     "paused_days": 0})
    return gaps


# ----------------------------- 数据水位 -----------------------------

def compute_watermark(db: Session, center_id: int, product_id: int,
                      window_from: date, window_to: date) -> dict:
    """按研究时间窗 [window_from, window_to] 计算实际数据水位。

    水位只统计质控通过的可用批次；失败/待校验批次单独列出但不进水位。
    """
    events = (
        db.query(RefreshEvent)
        .filter(RefreshEvent.center_id == center_id,
                RefreshEvent.product_id == product_id,
                RefreshEvent.partition_date >= window_from,
                RefreshEvent.partition_date <= window_to)
        .order_by(RefreshEvent.partition_date, RefreshEvent.id)
        .all()
    )
    grouped: dict[date, list[RefreshEvent]] = {}
    for e in events:
        grouped.setdefault(e.partition_date, []).append(e)

    available_dates: list[date] = []
    total_records = 0
    latest_available_at: datetime | None = None
    pending_partitions, failed_partitions, corrected_partitions = [], [], []
    partition_details = []
    for day, evs in sorted(grouped.items()):
        winner = _available_event_for_partition(evs)
        statuses = {e.status for e in evs}
        if winner is not None:
            available_dates.append(day)
            total_records += winner.record_count or 0
            if latest_available_at is None or winner.validated_at > latest_available_at:
                latest_available_at = winner.validated_at or winner.received_at
        if "已接收" in statuses and winner is None:
            pending_partitions.append(day.isoformat())
        if statuses <= set(FAILED_STATUSES) or (winner is None and "校验失败" in statuses):
            failed_partitions.append(day.isoformat())
        if any(e.event_kind == "更正发布" for e in evs):
            corrected_partitions.append(day.isoformat())
        partition_details.append({
            "partition_date": day.isoformat(),
            "available": winner is not None,
            "winning_batch_no": winner.batch_no if winner else None,
            "winning_revision_no": winner.revision_no if winner else None,
            "record_count": winner.record_count if winner else 0,
            "statuses": sorted(statuses),
            "event_kinds": sorted({e.event_kind for e in evs}),
        })

    return {
        "window_from": window_from.isoformat(),
        "window_to": window_to.isoformat(),
        "available_partition_count": len(available_dates),
        "available_partitions": [d.isoformat() for d in available_dates],
        "latest_available_partition": max(available_dates).isoformat() if available_dates else None,
        "latest_available_at": latest_available_at.isoformat() if latest_available_at else None,
        "total_records": total_records,
        "pending_qc_partitions": pending_partitions,
        "qc_failed_partitions": failed_partitions,
        "corrected_partitions": corrected_partitions,
        "partition_details": partition_details,
        "event_ids": sorted({e.id for e in events}),
    }


# ----------------------------- 就绪判定 -----------------------------

@dataclass
class ReadinessVerdict:
    state: str
    reason: str
    threshold_hours: float | None
    mode_used: str
    mode_note: str


def _verdict_for_partition(
    contract: RefreshContract,
    profile: dict,
    events: list[RefreshEvent],
    due_at: datetime,
    as_of: datetime,
    mode: str,
) -> ReadinessVerdict:
    """对单个应交付分区判定 及时/延迟/缺失/待校验。"""
    available = _available_event_for_partition(events)

    # 1) 尚无任何批次到达
    if not events:
        if as_of <= due_at:
            return ReadinessVerdict("缺失", f"截至评估时刻尚无批次到达，交付窗 {due_at:%Y-%m-%d %H:%M} 尚未截止",
                                    None, mode, "")
        return ReadinessVerdict("缺失", f"交付窗 {due_at:%Y-%m-%d %H:%M} 已过，仍无任何批次到达",
                                None, mode, "")

    # 2) 批次已生成/接收但质控未通过 → 不能把文件到达视为可用
    if available is None:
        if any(e.status == "校验失败" for e in events):
            reason = "批次已到达但质控失败，文件到达不等于可用数据：" + "；".join(
                sorted({e.fail_reason or "质控未通过" for e in events if e.status == "校验失败"}))
            return ReadinessVerdict("待校验", reason, None, mode, "")
        first_event = sorted(events, key=lambda e: e.received_at)[0]
        return ReadinessVerdict("待校验",
                                f"批次 {first_event.batch_no} 已接收，质控尚未完成，暂不可用于分析",
                                None, mode, "")

    # 3) 已有可用批次：首次发布 = 最早的可用非更正批次（失败/待校验批次不构成发布）
    first_pool = [e for e in events
                  if e.status in AVAILABLE_STATUSES and e.event_kind != "更正发布"]
    first_event = sorted(first_pool, key=lambda e: e.received_at)[0]
    mode_used, mode_note, threshold_hours = mode, "", None
    delay_hours = first_event.first_publish_delay_hours
    if mode == "statistical":
        stat = profile["statistical"]
        if not stat["usable"] or stat["ready_threshold_hours"] is None:
            mode_used = "fixed"
            mode_note = (f"历史已校验批次 {stat['history_size']} 个，少于统计模式要求 "
                         f"{stat['min_history_required']} 个，回退固定期限判定")
            threshold_hours = contract.expected_window_days * 24.0
            on_time = (delay_hours or 0) <= 0
        else:
            threshold_hours = stat["ready_threshold_hours"]
            on_time = (delay_hours or 0) <= threshold_hours
    else:
        threshold_hours = contract.expected_window_days * 24.0
        on_time = (delay_hours or 0) <= 0

    if on_time:
        reason = (f"首次发布延迟 {delay_hours} 小时，未超过"
                  + ("统计阈值" if mode_used == "statistical" else "固定交付窗")
                  + f"（阈值 {threshold_hours} 小时）")
        return ReadinessVerdict("及时", reason, threshold_hours, mode_used, mode_note)

    late_kind = "迟到补传" if first_event.event_kind == "迟到补传" else "全量刷新"
    reason = (f"首次发布延迟 {delay_hours} 小时，超过"
              + ("统计时效阈值" if mode_used == "statistical" else "固定交付窗")
              + f"（阈值 {threshold_hours} 小时），首次发布形式：{late_kind}")
    if mode_note:
        reason = mode_note + "；" + reason
    return ReadinessVerdict("延迟", reason, threshold_hours, mode_used, mode_note)


def evaluate_readiness(
    db: Session,
    project_id: int,
    center_id: int,
    product_id: int,
    analysis_cutoff: date,
    window_from: date,
    mode: str = "fixed",
    as_of: datetime | None = None,
    created_by: str = "system",
) -> ReadinessSnapshot:
    """就绪判定器：项目 × 产品 × 分析截止日 → 及时/延迟/缺失/待校验/预期无采集。

    研究窗内每个应交付分区独立判定，总体状态取最严重者；水位与证据冻结进快照。
    """
    if mode not in ("fixed", "statistical"):
        raise RefreshError("mode 仅支持 fixed/statistical")
    project = db.get(Project, project_id)
    center = db.get(ResearchCenter, center_id)
    if project is None or center is None:
        raise RefreshError("课题或研究中心不存在")
    contract = _get_contract(db, center_id, product_id)
    as_of = as_of or datetime.utcnow()

    profile = build_profile(db, center_id, product_id, window_from, analysis_cutoff)
    watermark = compute_watermark(db, center_id, product_id, window_from, analysis_cutoff)

    dows = set(scheduled_dow(center, contract))
    partition_verdicts = []
    severity = {"及时": 0, "预期无采集": 0, "延迟": 1, "缺失": 2, "待校验": 3}
    worst = "及时"
    for day in iter_expected_partitions(center, contract, window_from, analysis_cutoff):
        due_at = expected_due_for_partition(center, contract, day)
        pause = is_paused(db, center_id, product_id, day)
        if pause is not None:
            v = ReadinessVerdict("预期无采集",
                                 f"计划停诊/停采（{pause.reason or '停诊'}，{pause.pause_from}~{pause.pause_to}），不预期采集",
                                 None, mode, "")
            partition_verdicts.append({"partition_date": day.isoformat(), "state": v.state,
                                       "reason": v.reason, "expected_due_at": due_at.isoformat()})
        else:
            evs = (
                db.query(RefreshEvent)
                .filter(RefreshEvent.center_id == center_id,
                        RefreshEvent.product_id == product_id,
                        RefreshEvent.partition_date == day)
                .order_by(RefreshEvent.id)
                .all()
            )
            v = _verdict_for_partition(contract, profile, evs, due_at, as_of, mode)
            partition_verdicts.append({
                "partition_date": day.isoformat(), "state": v.state, "reason": v.reason,
                "expected_due_at": due_at.isoformat(),
                "threshold_hours": v.threshold_hours, "mode_used": v.mode_used,
                "mode_note": v.mode_note,
                "batch_nos": [e.batch_no for e in evs],
            })
        if severity[partition_verdicts[-1]["state"]] > severity[worst]:
            worst = partition_verdicts[-1]["state"]

    if not partition_verdicts:
        worst = "预期无采集"
        overall_reason = "研究时间窗内无任何排程分区"
    else:
        counters = {}
        for v in partition_verdicts:
            counters[v["state"]] = counters.get(v["state"], 0) + 1
        overall_reason = "；".join(f"{k} {v} 个分区" for k, v in sorted(counters.items()))

    evidence = {
        "mode_requested": mode,
        "contract": {
            "frequency": contract.frequency,
            "expected_window_days": contract.expected_window_days,
            "cutoff_time": contract.cutoff_time,
            "statistical_quantile": contract.statistical_quantile,
            "min_history_for_stat": contract.min_history_for_stat,
        },
        "weekday_schedule": sorted(dows),
        "profile_delay_hours": profile["delay_hours"],
        "statistical": profile["statistical"],
        "partition_verdicts": partition_verdicts,
        "referenced_event_ids": watermark["event_ids"],
        "as_of": as_of.isoformat(),
        "recalc_note": "本快照可由 referenced_event_ids 对应刷新事件与合约排程重新复算",
    }
    watermark_snapshot = {k: v for k, v in watermark.items() if k != "event_ids"}
    watermark_snapshot["referenced_event_ids"] = watermark["event_ids"]

    snapshot = ReadinessSnapshot(
        project_id=project_id, center_id=center_id, product_id=product_id,
        analysis_cutoff=analysis_cutoff, window_from=window_from, mode=mode,
        state=worst, reason=overall_reason,
        watermark_snapshot=watermark_snapshot, evidence=evidence,
        created_by=created_by,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def mark_superseded(db: Session, center_id: int, product_id: int,
                    partition_date: date) -> int:
    """新批次到达后，把引用了该分区且未标记的历史就绪快照置 superseded（内容不覆盖）。

    只重算涉及的产品分区与研究截止范围；旧快照保留冻结水位，审计仍可复算。
    """
    rows = (
        db.query(ReadinessSnapshot)
        .filter(ReadinessSnapshot.center_id == center_id,
                ReadinessSnapshot.product_id == product_id,
                ReadinessSnapshot.window_from <= partition_date,
                ReadinessSnapshot.analysis_cutoff >= partition_date,
                ReadinessSnapshot.superseded.is_(False))
        .all()
    )
    for row in rows:
        row.superseded = True
    db.flush()
    return len(rows)


def recompute_snapshot(db: Session, snapshot_id: int, as_of: datetime | None = None) -> dict:
    """由刷新事件重新复算一次历史快照，返回「当时冻结结论」与「当前复算结论」的对照。"""
    snap = db.get(ReadinessSnapshot, snapshot_id)
    if snap is None:
        raise RefreshError("就绪快照不存在")
    frozen = {
        "frozen_snapshot_id": snap.id,
        "frozen_state": snap.state,
        "frozen_reason": snap.reason,
        "frozen_watermark": snap.watermark_snapshot,
    }
    fresh = evaluate_readiness(
        db, snap.project_id, snap.center_id, snap.product_id,
        snap.analysis_cutoff, snap.window_from, mode=snap.mode,
        as_of=as_of, created_by="recompute",
    )
    fresh_state, fresh_reason, fresh_wm = fresh.state, fresh.reason, fresh.watermark_snapshot
    db.rollback()  # 复算只做对照，不落新快照
    return {
        **frozen,
        "recomputed_state": fresh_state,
        "recomputed_reason": fresh_reason,
        "recomputed_watermark": fresh_wm,
        "state_changed": fresh_state != frozen["frozen_state"],
    }
