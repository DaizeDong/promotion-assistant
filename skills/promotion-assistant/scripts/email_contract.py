"""Frozen email content and an explicit, verifiable helper request contract."""
import hashlib
import json
import re

CONTRACT = 'reviewed-email-v1'
EMAIL = re.compile(r"^[^\s@\"'<>]+@[^\s@\"'<>]+\.[^\s@\"'<>]+$")


def render(payload):
    """Every compliance-bearing component is part of the reviewed, transported body."""
    return '\n\n'.join(str(payload.get(field) or '') for field in
                       ('body', 'cta', 'physical_address', 'unsubscribe'))


def freeze(payload):
    result = dict(payload)
    result['rendered_body'] = render(result)
    return result


def request(payload):
    recipient, sender = payload.get('recipient'), payload.get('from_addr')
    if payload.get('email_helper_contract') != CONTRACT:
        raise ValueError('configure reviewed-email-v1 only after the helper supports its complete request and receipt')
    if not all(isinstance(address, str) and EMAIL.fullmatch(address) for address in (recipient, sender)):
        raise ValueError('email requires one valid recipient and sender')
    fields = ('subject', 'body', 'cta', 'physical_address', 'unsubscribe', 'idempotency_key')
    if any(not isinstance(payload.get(field), str) or not payload[field].strip() for field in fields):
        raise ValueError('email requires complete reviewed content and action identity')
    if payload.get('destination') != recipient or payload.get('rendered_body') != render(payload):
        raise ValueError('email destination or rendered body differs from frozen review')
    if any('\r' in payload[field] or '\n' in payload[field] for field in ('subject', 'from_addr', 'recipient')):
        raise ValueError('email header fields must be single-line')
    envelope = {'contract': CONTRACT, 'platform': 'email', 'idempotency_key': payload['idempotency_key'],
                'destination': recipient, 'recipient': recipient, 'sender': sender,
                'subject': payload['subject'], 'body': payload['rendered_body']}
    envelope['request_sha256'] = hashlib.sha256(json.dumps(
        envelope, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    return envelope


def matching(receipt, payload):
    """Never supply missing helper evidence from the expected request."""
    try:
        expected = request(payload)
    except (ValueError, TypeError):
        return False
    if not isinstance(receipt, dict) or receipt.get('status') not in {'sent', 'not_applied'}:
        return False
    if any(receipt.get(field) != expected[field] for field in
           ('contract', 'platform', 'idempotency_key', 'destination', 'recipient', 'sender', 'request_sha256')):
        return False
    proof = receipt.get('message_id' if receipt['status'] == 'sent' else 'evidence')
    return isinstance(proof, str) and bool(proof.strip())
