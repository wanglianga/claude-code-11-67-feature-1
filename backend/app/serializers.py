"""ORM → 字典序列化（接口出参统一在此组装）。"""
from .models import (
    AccessEvent, CollectionPause, DataProduct, EthicsApproval, ProductField,
    Project, ProjectMember, ProjectPurpose, QualificationBatch,
    QualificationInstance, QuotaAccount, QuotaReservation, ReadinessSnapshot,
    RefreshContract, RefreshEvent, ResearchCenter, UsageEvent, UsageReport, User,
)


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "role": u.role, "member_name": u.member_name}


def field_dict(f: ProductField) -> dict:
    return {
        "id": f.id, "field_name": f.field_name, "semantic": f.semantic,
        "data_type": f.data_type, "sensitivity_level": f.sensitivity_level,
        "tags": f.tags, "available_from": f.available_from.isoformat(),
        "available_to": f.available_to.isoformat(), "is_active": f.is_active,
    }


def product_dict(p: DataProduct, with_fields: bool = False) -> dict:
    d = {
        "id": p.id, "code": p.code, "name": p.name,
        "source_system": p.source_system, "update_frequency": p.update_frequency,
        "owner_dept": p.owner_dept, "description": p.description,
        "status": p.status, "catalog_version": p.catalog_version,
        "field_count": len(p.fields),
    }
    if with_fields:
        d["fields"] = [field_dict(f) for f in p.fields]
    return d


def purpose_dict(p: ProjectPurpose) -> dict:
    return {
        "id": p.id, "purpose_code": p.purpose_code, "description": p.description,
        "max_sensitivity_level": p.max_sensitivity_level,
        "forbidden_tags": p.forbidden_tags, "export_allowed": p.export_allowed,
    }


def member_dict(m: ProjectMember) -> dict:
    return {
        "id": m.id, "name": m.name, "role": m.role,
        "valid_from": m.valid_from.isoformat(), "valid_to": m.valid_to.isoformat(),
        "status": m.status,
    }


def ethics_dict(e: EthicsApproval) -> dict:
    return {
        "id": e.id, "approval_no": e.approval_no, "scope_subjects": e.scope_subjects,
        "allowed_purposes": e.allowed_purposes,
        "max_sensitivity_level": e.max_sensitivity_level,
        "forbidden_tags": e.forbidden_tags,
        "valid_from": e.valid_from.isoformat(), "valid_to": e.valid_to.isoformat(),
        "status": e.status,
    }


def project_dict(p: Project, detail: bool = False) -> dict:
    d = {
        "id": p.id, "code": p.code, "name": p.name, "pi_name": p.pi_name,
        "status": p.status, "start_date": p.start_date.isoformat(),
        "end_date": p.end_date.isoformat(),
    }
    if detail:
        d["purposes"] = [purpose_dict(x) for x in p.purposes]
        d["members"] = [member_dict(x) for x in p.members]
        d["ethics"] = [ethics_dict(x) for x in p.ethics]
    return d


def qualification_dict(q: QualificationInstance, detail: bool = False) -> dict:
    d = {
        "id": q.id, "batch_id": q.batch_id,
        "project_id": q.project_id, "project_code": q.project.code if q.project else None,
        "project_name": q.project.name if q.project else None,
        "product_id": q.product_id, "product_code": q.product.code if q.product else None,
        "product_name": q.product.name if q.product else None,
        "purpose_code": q.purpose_code, "status": q.status,
        "fail_reason": q.fail_reason,
        "valid_from": q.valid_from.isoformat() if q.valid_from else None,
        "valid_to": q.valid_to.isoformat() if q.valid_to else None,
        "version": q.version, "issued_at": q.issued_at.isoformat() if q.issued_at else None,
        "issued_by": q.issued_by,
        "revoked_at": q.revoked_at.isoformat() if q.revoked_at else None,
        "revoke_reason": q.revoke_reason,
        "field_count": len(q.field_projection or []),
        "catalog_version": q.catalog_version,
    }
    if detail:
        d["field_projection"] = q.field_projection
        d["covered_member_ids"] = q.covered_member_ids
        d["basis"] = q.basis
    return d


def batch_dict(b: QualificationBatch, with_items: bool = False) -> dict:
    d = {
        "id": b.id, "batch_no": b.batch_no, "title": b.title, "status": b.status,
        "total": b.total, "succeeded": b.succeeded, "failed": b.failed,
        "created_by": b.created_by, "created_at": b.created_at.isoformat(),
        "finished_at": b.finished_at.isoformat() if b.finished_at else None,
    }
    if with_items:
        d["items"] = [qualification_dict(q) for q in b.items]
    return d


def account_dict(a: QuotaAccount, active: int = 0) -> dict:
    return {
        "id": a.id, "project_id": a.project_id,
        "project_code": a.project.code if a.project else None,
        "project_name": a.project.name if a.project else None,
        "max_concurrent": a.max_concurrent, "active_reservations": active,
        "budget_query": a.budget_query, "used_query": a.used_query,
        "budget_export_rows": a.budget_export_rows, "used_export_rows": a.used_export_rows,
        "budget_compute_hours": a.budget_compute_hours, "used_compute_hours": a.used_compute_hours,
    }


def reservation_dict(r: QuotaReservation) -> dict:
    return {
        "id": r.id, "account_id": r.account_id, "kind": r.kind, "status": r.status,
        "access_event_id": r.access_event_id, "note": r.note,
        "created_at": r.created_at.isoformat(),
        "released_at": r.released_at.isoformat() if r.released_at else None,
    }


def usage_event_dict(e: UsageEvent, with_reports: bool = False) -> dict:
    d = {
        "id": e.id, "account_id": e.account_id, "kind": e.kind, "amount": e.amount,
        "idempotency_key": e.idempotency_key, "receipt_no": e.receipt_no,
        "access_event_id": e.access_event_id,
        "balance_after": e.balance_after, "created_at": e.created_at.isoformat(),
    }
    if with_reports:
        d["reports"] = [usage_report_dict(r) for r in e.reports]
    return d


def usage_report_dict(r: UsageReport) -> dict:
    return {
        "id": r.id, "event_id": r.event_id, "is_duplicate": r.is_duplicate,
        "note": r.note, "reported_at": r.reported_at.isoformat(),
    }


def access_event_dict(e: AccessEvent, detail: bool = False) -> dict:
    d = {
        "id": e.id, "request_id": e.request_id,
        "project_id": e.project_id, "product_id": e.product_id,
        "purpose_code": e.purpose_code,
        "member_id": e.member_id, "member_name": e.member_name,
        "qualification_id": e.qualification_id,
        "kind": e.kind, "status": e.status, "deny_reason": e.deny_reason,
        "requested_fields": e.requested_fields, "granted_fields": e.granted_fields,
        "created_at": e.created_at.isoformat(),
    }
    if detail:
        d["product_snapshot"] = e.product_snapshot
        d["qualification_snapshot"] = e.qualification_snapshot
        d["quota_snapshot"] = e.quota_snapshot
    return d


# ---------------- 刷新时效 ----------------

def center_dict(c: ResearchCenter) -> dict:
    return {
        "id": c.id, "code": c.code, "name": c.name,
        "weekday_schedule": c.weekday_schedule or [], "note": c.note,
    }


def contract_dict(c: RefreshContract) -> dict:
    return {
        "id": c.id, "center_id": c.center_id,
        "center_code": c.center.code if c.center else None,
        "center_name": c.center.name if c.center else None,
        "product_id": c.product_id,
        "product_code": c.product.code if c.product else None,
        "product_name": c.product.name if c.product else None,
        "frequency": c.frequency, "expected_window_days": c.expected_window_days,
        "cutoff_time": c.cutoff_time,
        "statistical_quantile": c.statistical_quantile,
        "min_history_for_stat": c.min_history_for_stat, "active": c.active,
    }


def pause_dict(p: CollectionPause) -> dict:
    return {
        "id": p.id, "center_id": p.center_id, "product_id": p.product_id,
        "pause_from": p.pause_from.isoformat(), "pause_to": p.pause_to.isoformat(),
        "reason": p.reason,
    }


def refresh_event_dict(e: RefreshEvent) -> dict:
    return {
        "id": e.id, "center_id": e.center_id,
        "center_code": e.center.code if e.center else None,
        "product_id": e.product_id,
        "product_code": e.product.code if e.product else None,
        "partition_date": e.partition_date.isoformat(),
        "batch_no": e.batch_no, "event_kind": e.event_kind, "status": e.status,
        "generated_at": e.generated_at.isoformat() if e.generated_at else None,
        "received_at": e.received_at.isoformat() if e.received_at else None,
        "validated_at": e.validated_at.isoformat() if e.validated_at else None,
        "qc_failed_at": e.qc_failed_at.isoformat() if e.qc_failed_at else None,
        "fail_reason": e.fail_reason, "record_count": e.record_count,
        "revision_no": e.revision_no, "correction_of_id": e.correction_of_id,
        "expected_due_at": e.expected_due_at.isoformat() if e.expected_due_at else None,
        "first_publish_delay_hours": e.first_publish_delay_hours,
        "correction_delay_hours": e.correction_delay_hours,
    }


def readiness_dict(s: ReadinessSnapshot) -> dict:
    return {
        "id": s.id, "project_id": s.project_id, "center_id": s.center_id,
        "product_id": s.product_id,
        "analysis_cutoff": s.analysis_cutoff.isoformat(),
        "window_from": s.window_from.isoformat(), "mode": s.mode,
        "state": s.state, "reason": s.reason,
        "watermark": s.watermark_snapshot, "evidence": s.evidence,
        "superseded": s.superseded, "created_by": s.created_by,
        "created_at": s.created_at.isoformat(),
    }
