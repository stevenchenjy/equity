"""Snapshot a private dashboard link; rendering never reads mutable config."""
import hashlib
import json
import re
from pathlib import Path


def publication_id(decision: dict):
    identity=json.dumps([decision.get('generated_at'),decision.get('decision_fingerprint'),decision.get('owner_requested_research')],
                        sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(identity).hexdigest()


def bind_dashboard_link(decision: dict, root: Path):
    config=root/'07_automation/dashboard.local/access.json'
    if not config.exists() or config.is_symlink(): return
    try:
        host=json.loads(config.read_text())['host']
        if not isinstance(host,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.ts\.net',host): return
        token=publication_id(decision)
        decision['dashboard_link']={'publication_id':token,'url':'https://'+host+'/?publication='+token}
    except (OSError,ValueError,KeyError,TypeError): return
