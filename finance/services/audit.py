"""Hash-chained audit trail. Every financial action calls record() inside its own transaction."""
import hashlib
import json
from datetime import timezone as dt_timezone

from django.db import connection, transaction
from django.utils import timezone

from accounts.utils import client_ip

from ..models import AuditEvent

GENESIS = "0" * 64
_ADVISORY_KEY = 7340002


def _normalise(value):
    """Round-trip through JSON so what we hash equals what the database returns."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev_hash, payload):
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


def _payload(*, seq, timestamp, actor_id, event_type, object_type, object_id,
             old_values, new_values, reason, refs):
    return {
        "seq": seq,
        "timestamp": timestamp.astimezone(dt_timezone.utc).isoformat(),
        "actor_id": actor_id,
        "event_type": event_type,
        "object_type": object_type,
        "object_id": object_id,
        "old": old_values,
        "new": new_values,
        "reason": reason,
        "refs": refs,
    }


def snapshot(obj, exclude=()):
    """Plain dict of an object's concrete fields (for old/new values)."""
    data = {}
    for field in obj._meta.concrete_fields:
        if field.name in exclude:
            continue
        data[field.name] = getattr(obj, field.attname)
    return _normalise(data)


def record(*, actor, event_type, obj=None, object_type="", object_id="", old=None, new=None,
           reason="", refs=None, request=None):
    """Append one event. Serialised with an advisory lock so the chain stays linear."""
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_ADVISORY_KEY])
        last = AuditEvent.objects.order_by("-seq").first()
        seq = last.seq + 1 if last else 1
        prev_hash = last.hash if last else GENESIS
        now = timezone.now()
        if obj is not None:
            object_type = object_type or type(obj).__name__
            object_id = object_id or str(obj.pk)
        old_n, new_n, refs_n = _normalise(old), _normalise(new), _normalise(refs or {})
        actor_obj = actor if getattr(actor, "is_authenticated", False) else None
        digest = _digest(prev_hash, _payload(
            seq=seq, timestamp=now, actor_id=getattr(actor_obj, "pk", None),
            event_type=event_type, object_type=object_type, object_id=str(object_id),
            old_values=old_n, new_values=new_n, reason=reason, refs=refs_n))
        return AuditEvent.objects.create(
            seq=seq, timestamp=now, actor=actor_obj,
            actor_label=(actor_obj.display_name if actor_obj else "system"),
            ip=client_ip(request) if request is not None else None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request is not None else ""),
            event_type=event_type, object_type=object_type, object_id=str(object_id),
            old_values=old_n, new_values=new_n, reason=reason, refs=refs_n,
            prev_hash=prev_hash, hash=digest)


def verify_chain():
    """Recompute the chain. Returns (ok, events_checked, message)."""
    prev_hash, expected_seq, checked = GENESIS, 1, 0
    for ev in AuditEvent.objects.order_by("seq").iterator():
        if ev.seq != expected_seq:
            return False, checked, f"Sequence gap before #{ev.seq} (expected #{expected_seq})."
        if ev.prev_hash != prev_hash:
            return False, checked, f"Event #{ev.seq} does not link to the previous event."
        payload = _payload(
            seq=ev.seq, timestamp=ev.timestamp, actor_id=ev.actor_id, event_type=ev.event_type,
            object_type=ev.object_type, object_id=ev.object_id, old_values=ev.old_values,
            new_values=ev.new_values, reason=ev.reason, refs=ev.refs)
        if _digest(prev_hash, payload) != ev.hash:
            return False, checked, f"Event #{ev.seq} content does not match its hash."
        prev_hash, expected_seq, checked = ev.hash, expected_seq + 1, checked + 1
    return True, checked, f"Audit chain intact ({checked} events)."