"""刷新时效画像与就绪判定验收测试。

覆盖题目全部验收点：
- 固定期限 vs 统计阈值两种判定模式的差异与回退；
- 周末停采 / 计划停诊 → 预期无采集而非迟交；
- 质控失败只算文件到达、不进水位，补传后才可用；
- 历史更正与首次发布延迟分离统计，更正不是全量刷新；
- 长期无新批次的连续缺口与数据水位；
- 就绪快照冻结水位、新批次只标记涉及分区（superseded）、可由事件复算；
- 增量重算范围、登记约束与权限。
"""
from datetime import date, datetime, time, timedelta

from tests.conftest import login

from app.db import SessionLocal
from app.models import RefreshEvent
from app.services import refresh as svc


TODAY = date.today()
D = timedelta(days=1)


# ----------------------------- 工具 -----------------------------

def _dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def _weekdays(end_back: int, n: int) -> list[date]:
    """返回以 TODAY-end_back 为最后一天、向前数 n 个工作日的日期列表（升序）。"""
    end = TODAY - end_back * D
    out, day = [], end
    while len(out) < n:
        if day.isoweekday() <= 5:
            out.append(day)
        day -= D
    return sorted(out)


def _ids(client, headers):
    products = {p["code"]: p["id"] for p in client.get("/api/catalog/products", headers=headers).json()}
    projects = {p["code"]: p["id"] for p in client.get("/api/projects", headers=headers).json()}
    centers = {c["code"]: c["id"] for c in client.get("/api/refresh/centers", headers=headers).json()}
    return products, projects, centers


def _create_controlled_center(client, admin, product_id, min_history=3):
    """创建独立测试中心与按日合约（交付窗 1 天、18:00 截止），并灌入 10 个稳定历史分区。"""
    r = client.post("/api/refresh/centers", headers=admin, json={
        "code": "RC-T-" + datetime.utcnow().strftime("%H%M%S%f"),
        "name": "判定模式对照中心", "weekday_schedule": [1, 2, 3, 4, 5]})
    assert r.status_code == 200, r.text
    center_id = r.json()["id"]
    r = client.post("/api/refresh/contracts", headers=admin, json={
        "center_id": center_id, "product_id": product_id, "frequency": "每日",
        "expected_window_days": 1, "cutoff_time": "18:00",
        "min_history_for_stat": min_history})
    assert r.status_code == 200, r.text
    # 历史批次全部在截止前 9 小时到达并通过质控 → 统计阈值约 -9h
    for day in _weekdays(12, 10):
        ev = client.post("/api/refresh/events", headers=admin, json={
            "center_id": center_id, "product_id": product_id,
            "partition_date": day.isoformat(), "received_at": _dt(day + D, 9).isoformat(),
            "record_count": 100}).json()["event"]
        client.post(f"/api/refresh/events/{ev['id']}/qc-pass", headers=admin,
                    json={"validated_at": _dt(day + D, 12).isoformat(), "record_count": 100})
    return center_id


def _readiness(client, headers, project_id, center_id, product_id, cutoff, win_from, mode):
    return client.post("/api/refresh/readiness", headers=headers, json={
        "project_id": project_id, "center_id": center_id, "product_id": product_id,
        "analysis_cutoff": cutoff.isoformat(), "window_from": win_from.isoformat(),
        "mode": mode}).json()


def _verdict(snapshot, partition: date):
    return next(v for v in snapshot["evidence"]["partition_verdicts"]
                if v["partition_date"] == partition.isoformat())


# ----------------------------- 1. 种子画像指标可由事件复算 -----------------------------

def test_seed_profile_metrics(client):
    admin = login(client, "admin", "admin123")
    products, _, centers = _ids(client, admin)
    r = client.get("/api/refresh/profiles", headers=admin, params={
        "center_id": centers["RC-01"], "product_id": products["P-LAB"],
        "window_from": (TODAY - 27 * D).isoformat(), "window_to": TODAY.isoformat()})
    assert r.status_code == 200
    p = r.json()
    # 延迟分位数齐全；迟到补传分区的首次发布延迟 64h 为最大值
    dh = p["delay_hours"]
    assert dh["p50"] is not None and dh["p90"] is not None and dh["max"] == 64.0
    # 迟到补传比例 = 1/18
    assert p["backfill_partition_count"] == 1
    assert 0 < p["backfill_ratio"] < 0.1
    # 更正延迟独立统计，不混入首次发布延迟
    assert p["correction_count"] == 1
    assert p["correction_delay_hours"]["max"] == 126.33
    assert all(v != 126.33 for v in dh.values() if v is not None)
    # 一个质控失败（已被补传替代）、一个待校验
    assert p["qc_failed_count"] == 1 and p["pending_qc_count"] == 1
    # 历史充足，统计模式可用
    assert p["statistical"]["usable"] is True
    assert p["statistical"]["history_size"] >= p["statistical"]["min_history_required"]


# ----------------------------- 2. 固定期限 vs 统计阈值 -----------------------------

def test_fixed_vs_statistical_mode(client):
    admin = login(client, "admin", "admin123")
    products, projects, _ = _ids(client, admin)
    center_id = _create_controlled_center(client, admin, products["P-LAB"])
    target = _weekdays(2, 1)[0]  # 截止窗已过的工作日

    # 批次在截止前 1 小时到达：历史上 90% 批次比这更早
    ev = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": target.isoformat(),
        "received_at": _dt(target + D, 17).isoformat(), "record_count": 50}).json()["event"]
    client.post(f"/api/refresh/events/{ev['id']}/qc-pass", headers=admin,
                json={"validated_at": _dt(target + D, 17, 30).isoformat()})

    win_from = _weekdays(12, 10)[0]
    fixed = _readiness(client, admin, projects["PRJ-A"], center_id, products["P-LAB"],
                       target, win_from, "fixed")
    stat = _readiness(client, admin, projects["PRJ-A"], center_id, products["P-LAB"],
                      target, win_from, "statistical")
    # 固定期限：未超交付窗 → 及时
    assert _verdict(fixed, target)["state"] == "及时"
    assert _verdict(fixed, target)["mode_used"] == "fixed"
    # 统计阈值：晚于历史 p90（约 -9h）→ 延迟，阈值与原因可解释
    sv = _verdict(stat, target)
    assert sv["state"] == "延迟" and sv["mode_used"] == "statistical"
    assert sv["threshold_hours"] is not None and sv["threshold_hours"] < 0

    # 超过交付窗 2 小时：两种模式都判延迟
    late_day = _weekdays(1, 1)[0]
    ev2 = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": late_day.isoformat(),
        "received_at": _dt(late_day + D, 20).isoformat()}).json()["event"]
    client.post(f"/api/refresh/events/{ev2['id']}/qc-pass", headers=admin,
                json={"validated_at": _dt(late_day + D, 21).isoformat()})
    fixed2 = _readiness(client, admin, projects["PRJ-A"], center_id, products["P-LAB"],
                        late_day, win_from, "fixed")
    assert _verdict(fixed2, late_day)["state"] == "延迟"


def test_statistical_falls_back_to_fixed_when_history_insufficient(client):
    admin = login(client, "admin", "admin123")
    products, projects, centers = _ids(client, admin)
    # RC-03 × P-BIO 每月合约要求 4 个历史批次，种子恰好 4 个；新建高门槛合约验证回退
    r = client.post("/api/refresh/centers", headers=admin, json={
        "code": "RC-RARE", "name": "稀疏历史中心", "weekday_schedule": [1, 2, 3, 4, 5]})
    center_id = r.json()["id"]
    client.post("/api/refresh/contracts", headers=admin, json={
        "center_id": center_id, "product_id": products["P-BIO"], "frequency": "每月",
        "expected_window_days": 3, "min_history_for_stat": 8})
    m = (TODAY.replace(day=1) - D).replace(day=1)
    ev = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-BIO"],
        "partition_date": m.isoformat(), "received_at": _dt(m + D, 10).isoformat()}).json()["event"]
    client.post(f"/api/refresh/events/{ev['id']}/qc-pass", headers=admin,
                json={"validated_at": _dt(m + D, 15).isoformat()})
    snap = _readiness(client, admin, projects["PRJ-C"], center_id, products["P-BIO"],
                      TODAY, m, "statistical")
    v = snap["evidence"]["partition_verdicts"][0]
    assert v["mode_used"] == "fixed" and "回退固定期限" in v["mode_note"]


# ----------------------------- 3. 质控失败 ≠ 可用；补传后承担水位 -----------------------------

def test_qc_failed_not_usable_until_backfill(client):
    admin = login(client, "admin", "admin123")
    products, projects, _ = _ids(client, admin)
    center_id = _create_controlled_center(client, admin, products["P-LAB"])
    target = _weekdays(2, 1)[0]

    ev = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": target.isoformat(),
        "received_at": _dt(target + D, 8).isoformat(), "record_count": 999}).json()["event"]
    fr = client.post(f"/api/refresh/events/{ev['id']}/qc-fail", headers=admin,
                     json={"failed_at": _dt(target + D, 10).isoformat(),
                           "reason": "值域校验失败"})
    assert fr.json()["event"]["status"] == "校验失败"

    win_from = _weekdays(12, 10)[0]
    snap = _readiness(client, admin, projects["PRJ-A"], center_id, products["P-LAB"],
                      target, win_from, "fixed")
    v = _verdict(snap, target)
    assert v["state"] == "待校验" and "质控失败" in v["reason"]
    # 失败批次不进水位
    wm = snap["watermark"]
    assert target.isoformat() not in wm["available_partitions"]
    assert target.isoformat() in wm["qc_failed_partitions"]
    assert wm["total_records"] == 1000  # 仅 10 个历史分区 × 100

    # 迟到补传通过质控 → 分区转为可用，首次发布延迟按补传接收时间计
    bf = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": target.isoformat(), "event_kind": "迟到补传",
        "received_at": _dt(target + 4 * D, 11).isoformat(),
        "record_count": 888}).json()["event"]
    client.post(f"/api/refresh/events/{bf['id']}/qc-pass", headers=admin,
                json={"validated_at": _dt(target + 4 * D, 14).isoformat(),
                      "record_count": 888})
    snap2 = _readiness(client, admin, projects["PRJ-A"], center_id, products["P-LAB"],
                       target, win_from, "fixed")
    v2 = _verdict(snap2, target)
    assert v2["state"] == "延迟" and "迟到补传" in v2["reason"]
    wm2 = snap2["watermark"]
    assert target.isoformat() in wm2["available_partitions"]
    detail = next(d for d in wm2["partition_details"] if d["partition_date"] == target.isoformat())
    assert detail["winning_batch_no"] == bf["batch_no"] and detail["record_count"] == 888


# ----------------------------- 4. 更正发布与首次发布延迟分离 -----------------------------

def test_correction_separates_publish_and_correction_delay(client):
    admin = login(client, "admin", "admin123")
    products, _, _ = _ids(client, admin)
    center_id = _create_controlled_center(client, admin, products["P-LAB"])
    target = _weekdays(2, 1)[0]

    v1 = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": target.isoformat(),
        "received_at": _dt(target + D, 9).isoformat(), "record_count": 100}).json()["event"]
    client.post(f"/api/refresh/events/{v1['id']}/qc-pass", headers=admin,
                json={"validated_at": _dt(target + D, 11).isoformat()})
    # 更正必须指向已校验批次；不能把失败批次当更正对象
    bad = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": (TODAY - 30 * D).isoformat(), "event_kind": "更正发布",
        "received_at": _dt(TODAY - 29 * D, 9).isoformat()})
    assert bad.status_code == 400

    v2 = client.post("/api/refresh/events", headers=admin, json={
        "center_id": center_id, "product_id": products["P-LAB"],
        "partition_date": target.isoformat(), "event_kind": "更正发布",
        "received_at": _dt(target + 3 * D, 15).isoformat(),
        "correction_of_id": v1["id"], "record_count": 104}).json()["event"]
    client.post(f"/api/refresh/events/{v2['id']}/qc-pass", headers=admin,
                json={"validated_at": _dt(target + 3 * D, 16).isoformat()})

    db = SessionLocal()
    try:
        old_ev = db.get(RefreshEvent, v1["id"])
        new_ev = db.get(RefreshEvent, v2["id"])
        assert old_ev.status == "已更正" and new_ev.status == "已校验"
        assert new_ev.revision_no == 2
        # 更正延迟 ≈ 54h，独立于首次发布延迟；旧批次的首次发布延迟保持 -9h 不被覆盖
        assert new_ev.correction_delay_hours == 54.0
        assert old_ev.first_publish_delay_hours == -9.0
        profile = svc.build_profile(db, center_id, products["P-LAB"],
                                    TODAY - 40 * D, TODAY)
        assert profile["correction_count"] == 1
        assert profile["correction_delay_hours"]["max"] == 54.0
        # 更正事件不进入首次发布延迟分布
        assert profile["delay_hours"]["max"] <= 0
        wm = svc.compute_watermark(db, center_id, products["P-LAB"], target, target)
        assert wm["latest_available_partition"] == target.isoformat()
        assert target.isoformat() in wm["corrected_partitions"]
        assert wm["partition_details"][0]["winning_revision_no"] == 2
    finally:
        db.close()


# ----------------------------- 5. 周末停采与计划停诊 → 预期无采集 -----------------------------

def test_weekend_and_pause_are_not_late(client):
    admin = login(client, "admin", "admin123")
    products, projects, centers = _ids(client, admin)
    # RC-01 × P-LAB 在 TODAY-15..TODAY-13 有计划停采
    r = client.post("/api/refresh/readiness", headers=admin, json={
        "project_id": projects["PRJ-A"], "center_id": centers["RC-01"],
        "product_id": products["P-LAB"],
        "analysis_cutoff": (TODAY - 13 * D).isoformat(),
        "window_from": (TODAY - 16 * D).isoformat(), "mode": "fixed"})
    snap = r.json()
    states = {v["partition_date"]: v["state"] for v in snap["evidence"]["partition_verdicts"]}
    # 停采窗口 TODAY-15..TODAY-13 内的工作日（窗口跨周末，取其中工作日）
    paused = next(TODAY - k * D for k in (15, 14, 13)
                  if (TODAY - k * D).isoweekday() <= 5)
    assert states[paused.isoformat()] == "预期无采集"
    # 周末根本不作为预期分区枚举
    saturday = next(TODAY - k * D for k in range(13, 17)
                    if (TODAY - k * D).isoweekday() == 6)
    assert saturday.isoformat() not in states
    # 停诊分区不参与最坏状态判定：窗口内其余分区可用 → 总体不为缺失/延迟
    assert snap["state"] in ("及时", "预期无采集")

    # 新建停诊窗口直接验证
    target = _weekdays(3, 1)[0]
    client.post("/api/refresh/pauses", headers=admin, json={
        "center_id": centers["RC-01"], "product_id": products["P-IMG"],
        "pause_from": target.isoformat(), "pause_to": target.isoformat(),
        "reason": "设备保养"})
    snap2 = _readiness(client, admin, projects["PRJ-B"], centers["RC-01"],
                       products["P-IMG"], target, target, "fixed")
    assert snap2["evidence"]["partition_verdicts"][0]["state"] == "预期无采集"
    assert "设备保养" in snap2["evidence"]["partition_verdicts"][0]["reason"]


# ----------------------------- 6. 长期无新批次：连续缺口与水位 -----------------------------

def test_long_gap_and_watermark(client):
    admin = login(client, "admin", "admin123")
    products, projects, centers = _ids(client, admin)
    r = client.get("/api/refresh/profiles", headers=admin, params={
        "center_id": centers["RC-03"], "product_id": products["P-LAB"],
        "window_from": (TODAY - 24 * D).isoformat(), "window_to": TODAY.isoformat()})
    profile = r.json()
    assert profile["longest_gap"] is not None and profile["longest_gap"]["days"] >= 4
    # 缺口区间可复算：列出的每个缺口确实无可用分区
    gap_dates = set()
    for g in profile["gaps"]:
        d = date.fromisoformat(g["from"])
        while d <= date.fromisoformat(g["to"]):
            gap_dates.add(d.isoformat())
            d += D
    snap = _readiness(client, admin, projects["PRJ-A"], centers["RC-03"],
                      products["P-LAB"], TODAY, TODAY - 24 * D, "fixed")
    assert snap["state"] == "缺失"
    wm = snap["watermark"]
    assert wm["latest_available_partition"] == (TODAY - 10 * D).isoformat()
    assert wm["total_records"] > 0
    assert gap_dates and all(d not in wm["available_partitions"] for d in gap_dates)


# ----------------------------- 7. 周/月产品按周期枚举分区 -----------------------------

def test_weekly_and_monthly_partition_enumeration(client):
    admin = login(client, "admin", "admin123")
    products, projects, centers = _ids(client, admin)
    # 按周：8 个周一分区，而不是窗内全部工作日
    monday = TODAY - TODAY.isoweekday() * D + D
    snap = _readiness(client, admin, projects["PRJ-B"], centers["RC-02"],
                      products["P-FU"], TODAY, monday - 49 * D, "statistical")
    verdicts = snap["evidence"]["partition_verdicts"]
    assert len(verdicts) == 8
    assert all(date.fromisoformat(v["partition_date"]).isoweekday() == 1 for v in verdicts)
    assert sum(1 for v in verdicts if v["state"] == "延迟") == 1
    # 按月：种子恰好 4 个月初分区，截止到上月末避免把本月未到期分区计入
    first_of_month = TODAY.replace(day=1)
    earliest_month = first_of_month
    for _ in range(4):
        earliest_month = (earliest_month - D).replace(day=1)
    snap_m = _readiness(client, admin, projects["PRJ-C"], centers["RC-03"],
                        products["P-BIO"], first_of_month - D, earliest_month, "fixed")
    mv = snap_m["evidence"]["partition_verdicts"]
    assert len(mv) == 4
    assert all(date.fromisoformat(v["partition_date"]).day == 1 for v in mv)


# ----------------------------- 8. 快照冻结、增量标记与复算 -----------------------------

def test_snapshot_frozen_superseded_and_recompute(client):
    admin = login(client, "admin", "admin123")
    products, projects, centers = _ids(client, admin)
    win_from = TODAY - 24 * D
    snap = _readiness(client, admin, projects["PRJ-A"], centers["RC-01"],
                      products["P-LAB"], TODAY - 3 * D, win_from, "fixed")
    sid = snap["id"]
    frozen_wm = client.get(f"/api/refresh/readiness/{sid}", headers=admin).json()["watermark"]
    assert snap["evidence"]["referenced_event_ids"]

    # 新批次落在快照引用的分区范围内 → 仅标记 superseded，冻结内容不变
    target = TODAY - 5 * D
    r = client.post("/api/refresh/events", headers=admin, json={
        "center_id": centers["RC-01"], "product_id": products["P-LAB"],
        "partition_date": target.isoformat(), "event_kind": "迟到补传",
        "received_at": _dt(TODAY - 4 * D, 9).isoformat(), "record_count": 12})
    assert r.status_code == 200
    assert r.json()["snapshots_marked_superseded"] >= 1
    got = client.get(f"/api/refresh/readiness/{sid}", headers=admin).json()
    assert got["superseded"] is True
    assert got["watermark"] == frozen_wm  # 旧快照保留所引用水位

    # 由刷新事件复算：对照冻结结论，证据链可还原
    rc = client.post(f"/api/refresh/readiness/{sid}/recompute", headers=admin).json()
    assert rc["frozen_state"] == snap["state"]
    assert rc["frozen_watermark"] == frozen_wm
    assert "recomputed_watermark" in rc and "state_changed" in rc

    # 范围外的新批次（另一产品、且该分区无历史事件）不标记该快照（增量只重算涉及的分区/截止范围）
    outside = client.post("/api/refresh/events", headers=admin, json={
        "center_id": centers["RC-01"], "product_id": products["P-IMG"],
        "partition_date": (TODAY - 20 * D).isoformat(),
        "received_at": _dt(TODAY - 19 * D, 8).isoformat()})
    assert outside.status_code == 200
    assert outside.json()["snapshots_marked_superseded"] == 0


# ----------------------------- 9. 登记约束 -----------------------------

def test_register_guards(client):
    admin = login(client, "admin", "admin123")
    products, _, centers = _ids(client, admin)
    target = _weekdays(2, 1)[0]
    payload = {
        "center_id": centers["RC-01"], "product_id": products["P-LAB"],
        "partition_date": target.isoformat(), "received_at": _dt(target + D, 9).isoformat()}
    # 种子里该分区已有全量刷新 → 重复全量刷新拒绝
    assert client.post("/api/refresh/events", headers=admin, json=payload).status_code == 400
    # 迟到补传/更正不能指向不存在历史的分区
    fresh_day = TODAY - 40 * D
    r = client.post("/api/refresh/events", headers=admin, json={
        **payload, "partition_date": fresh_day.isoformat(), "event_kind": "迟到补传"})
    assert r.status_code == 400
    # 分析师无权登记事件
    zm = login(client, "zhangmin", "zhang123")
    assert client.post("/api/refresh/events", headers=zm, json=payload).status_code == 403
    # 但分析师可查看画像
    assert client.get("/api/refresh/profiles", headers=zm, params={
        "center_id": centers["RC-01"], "product_id": products["P-LAB"]}).status_code == 200


# ----------------------------- 10. 就绪原因与水位可直接展示 -----------------------------

def test_readiness_reason_and_watermark_shape(client):
    admin = login(client, "admin", "admin123")
    products, projects, centers = _ids(client, admin)
    snap = _readiness(client, admin, projects["PRJ-A"], centers["RC-01"],
                      products["P-LAB"], TODAY, TODAY - 12 * D, "fixed")
    # 总体状态 + 分区级原因 + 实际水位同时给出，而不是只有红黄状态
    assert snap["state"] in ("及时", "延迟", "缺失", "待校验", "预期无采集")
    assert snap["reason"]
    wm = snap["watermark"]
    for key in ("available_partition_count", "available_partitions", "latest_available_partition",
                "latest_available_at", "total_records", "pending_qc_partitions",
                "qc_failed_partitions", "corrected_partitions", "partition_details"):
        assert key in wm
    assert wm["available_partition_count"] == len(wm["available_partitions"])
    for v in snap["evidence"]["partition_verdicts"]:
        assert v["reason"] and v["expected_due_at"]
