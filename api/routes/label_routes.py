"""Wallet labels, tags, mixers, bridges and risk-check endpoints."""

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from sqlalchemy import func

label_bp = Blueprint('labels', __name__)


# ── helpers ─────────────────────────────────────────────────────────────

def _get_risk_level(is_mixer: bool, is_bridge: bool, tags: list) -> str:
    """Determine risk level based on flags and tags."""
    if is_mixer:
        return "high"

    level_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    tag_levels = [
        t.category.risk_level
        for t in tags
        if t.category and t.category.risk_level
    ]
    if tag_levels:
        return max(tag_levels, key=lambda l: level_rank.get(l, 0))

    if is_bridge:
        return "medium"

    return "low"


# ── label CRUD ──────────────────────────────────────────────────────────

@label_bp.route("/labels/import", methods=['POST'])
def trigger_labels_import():
    """Trigger import of wallet labels from eth-labels API."""
    from api.tasks.import_labels_task import import_labels_from_api

    data = request.get_json() if request.is_json else {}
    chain_ids = data.get('chain_ids')
    label_types = data.get('label_types')

    task = import_labels_from_api.delay(chain_ids=chain_ids, label_types=label_types)
    return jsonify({
        "message": "Labels import task submitted",
        "task_id": task.id,
        "chain_ids": chain_ids or "all",
        "label_types": label_types or "default"
    }), 202


@label_bp.route("/labels/lookup/<address>", methods=['GET'])
def lookup_address_labels(address):
    """Look up labels for a specific address."""
    from api.application.erc20models import WalletLabel, CHAIN_ID_TO_TRIGRAM
    from api.tasks.import_labels_task import import_labels_for_address

    fetch_if_missing = request.args.get('fetch', 'false').lower() == 'true'

    try:
        session = g.db_session
        labels = session.query(WalletLabel).filter(
            WalletLabel.address == address.lower()
        ).all()

        if labels:
            return jsonify({
                "address": address,
                "labels": [
                    {
                        "id": label.id,
                        "chain_id": label.chain_id,
                        "chain": CHAIN_ID_TO_TRIGRAM.get(label.chain_id, 'UNKNOWN'),
                        "label": label.label,
                        "label_type": label.label_type,
                        "name_tag": label.name_tag,
                        "source": label.source,
                        "confidence": label.confidence,
                        "is_trusted": label.is_trusted,
                        "validated_by": label.validated_by,
                        "notes": label.notes
                    }
                    for label in labels
                ],
                "source": "database"
            }), 200

        if fetch_if_missing:
            task = import_labels_for_address.delay(address)
            return jsonify({
                "address": address,
                "labels": [],
                "message": "No local labels found. API lookup started.",
                "task_id": task.id,
                "source": "pending_api"
            }), 202

        return jsonify({"address": address, "labels": [], "source": "database"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@label_bp.route("/labels/wallet/<address>", methods=['POST'])
def add_wallet_label(address):
    """Add a manual label to a wallet address."""
    from api.application.erc20models import WalletLabel, TRIGRAM_TO_CHAIN_ID

    data = request.get_json()

    label = data.get('label')
    chain = data.get('chain', 'ETH').upper()
    label_type = data.get('label_type')
    name_tag = data.get('name_tag')
    notes = data.get('notes')
    is_trusted = data.get('is_trusted', False)
    validated_by = data.get('validated_by')

    if not label:
        return jsonify({"error": "Missing required field: label"}), 400

    chain_id = TRIGRAM_TO_CHAIN_ID.get(chain)
    if chain_id is None:
        return jsonify({"error": f"Unknown chain: {chain}. Use ETH, POL, BSC, or BASE"}), 400

    try:
        session = g.db_session
        existing = session.query(WalletLabel).filter_by(
            address=address.lower(), chain_id=chain_id, label=label
        ).first()

        if existing:
            existing.label_type = label_type or existing.label_type
            existing.name_tag = name_tag or existing.name_tag
            existing.notes = notes or existing.notes
            existing.is_trusted = is_trusted
            existing.validated_by = validated_by
            existing.validated_at = datetime.now(timezone.utc) if is_trusted else existing.validated_at
            existing.updated_at = datetime.now(timezone.utc)
            session.commit()
            return jsonify({
                "message": "Label updated",
                "id": existing.id,
                "address": address.lower(),
                "label": label
            }), 200

        wallet_label = WalletLabel(
            address=address.lower(),
            chain_id=chain_id,
            label=label,
            label_type=label_type,
            name_tag=name_tag,
            source='manual',
            confidence=1.0,
            is_trusted=is_trusted,
            validated_by=validated_by,
            validated_at=datetime.now(timezone.utc) if is_trusted else None,
            notes=notes
        )
        session.add(wallet_label)
        session.commit()

        return jsonify({
            "message": "Label created",
            "id": wallet_label.id,
            "address": address.lower(),
            "label": label,
            "chain": chain
        }), 201

    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@label_bp.route("/labels/wallet/<address>", methods=['DELETE'])
def delete_wallet_label(address):
    """Delete a label from a wallet address."""
    from api.application.erc20models import WalletLabel, TRIGRAM_TO_CHAIN_ID

    label = request.args.get('label')
    chain = request.args.get('chain', 'ETH').upper()

    if not label:
        return jsonify({"error": "Missing required parameter: label"}), 400

    chain_id = TRIGRAM_TO_CHAIN_ID.get(chain)
    if chain_id is None:
        return jsonify({"error": f"Unknown chain: {chain}"}), 400

    try:
        session = g.db_session
        deleted = session.query(WalletLabel).filter_by(
            address=address.lower(), chain_id=chain_id, label=label
        ).delete()
        session.commit()

        if deleted:
            return jsonify({
                "message": "Label deleted",
                "address": address.lower(),
                "label": label,
                "chain": chain
            }), 200
        else:
            return jsonify({"error": "Label not found"}), 404

    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@label_bp.route("/labels/validate/<int:label_id>", methods=['POST'])
def validate_label(label_id):
    """Mark a label as trusted/validated by an analyst."""
    from api.application.erc20models import WalletLabel

    data = request.get_json() or {}
    validated_by = data.get('validated_by', 'analyst')
    is_trusted = data.get('is_trusted', True)
    notes = data.get('notes')

    try:
        session = g.db_session
        label = session.query(WalletLabel).filter_by(id=label_id).first()
        if not label:
            return jsonify({"error": "Label not found"}), 404

        label.is_trusted = is_trusted
        label.validated_by = validated_by
        label.validated_at = datetime.now(timezone.utc)
        if notes:
            label.notes = notes
        label.updated_at = datetime.now(timezone.utc)
        session.commit()

        return jsonify({
            "message": "Label validated",
            "id": label_id,
            "is_trusted": is_trusted,
            "validated_by": validated_by
        }), 200

    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@label_bp.route("/labels/types", methods=['GET'])
def list_label_types():
    """List all available label types."""
    from api.application.erc20models import LabelType

    try:
        session = g.db_session
        label_types = session.query(LabelType).order_by(LabelType.priority.desc()).all()
        return jsonify({
            "label_types": [
                {"name": lt.name, "description": lt.description, "color": lt.color, "priority": lt.priority}
                for lt in label_types
            ]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@label_bp.route("/labels/stats", methods=['GET'])
def labels_stats():
    """Get statistics about wallet labels in the database."""
    from api.application.erc20models import WalletLabel, LabelType, KnownBridge, CHAIN_ID_TO_TRIGRAM

    try:
        session = g.db_session

        chain_counts = session.query(
            WalletLabel.chain_id, func.count(WalletLabel.id)
        ).group_by(WalletLabel.chain_id).all()

        type_counts = session.query(
            WalletLabel.label_type, func.count(WalletLabel.id)
        ).group_by(WalletLabel.label_type).all()

        source_counts = session.query(
            WalletLabel.source, func.count(WalletLabel.id)
        ).group_by(WalletLabel.source).all()

        total_labels = session.query(WalletLabel).count()
        trusted_labels = session.query(WalletLabel).filter_by(is_trusted=True).count()
        known_bridges = session.query(KnownBridge).count()

        return jsonify({
            "total_labels": total_labels,
            "trusted_labels": trusted_labels,
            "known_bridges": known_bridges,
            "by_chain": {CHAIN_ID_TO_TRIGRAM.get(cid, str(cid)): cnt for cid, cnt in chain_counts},
            "by_type": {lt or 'unknown': cnt for lt, cnt in type_counts},
            "by_source": {src: cnt for src, cnt in source_counts}
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@label_bp.route("/labels/categories", methods=['GET'])
def list_label_categories():
    """List label categories."""
    from api.services.data_access import DataAccess

    data = DataAccess(g.db_session)
    categories = data.get_label_categories()

    return jsonify({
        "categories": [
            {"name": c.name, "description": c.description, "risk_level": c.risk_level, "color": c.color, "priority": c.priority}
            for c in categories
        ],
        "total": len(categories)
    }), 200


# ── tags ────────────────────────────────────────────────────────────────

@label_bp.route("/tags/<address>", methods=['GET'])
def get_wallet_tags(address):
    """Get tags for a wallet."""
    from api.services.data_access import DataAccess

    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    tags = data.get_wallet_tags(address, chain_code=chain)

    return jsonify({
        "address": address,
        "chain": chain,
        "tags": [
            {
                "id": t.id, "tag": t.tag, "chain": t.chain_code,
                "source": t.source, "confidence": t.confidence,
                "category": t.category.name if t.category else None,
                "risk_level": t.category.risk_level if t.category else None
            }
            for t in tags
        ],
        "total": len(tags)
    }), 200


@label_bp.route("/tags/<address>", methods=['POST'])
def add_wallet_tag(address):
    """Add tag to a wallet."""
    from api.services.data_access import DataAccess

    data = DataAccess(g.db_session)
    body = request.get_json() or {}
    tag = body.get('tag')
    chain = (body.get('chain') or 'ETH').upper()
    source = body.get('source', 'manual')
    confidence = float(body.get('confidence', 1.0))

    if not tag:
        return jsonify({"error": "tag is required"}), 400

    wt = data.add_wallet_tag(address, chain, tag, source=source, confidence=confidence)
    g.db_session.commit()

    return jsonify({
        "id": wt.id, "address": wt.address, "chain": wt.chain_code,
        "tag": wt.tag, "source": wt.source, "confidence": wt.confidence
    }), 201


# ── known entities ──────────────────────────────────────────────────────

@label_bp.route("/mixers", methods=['GET'])
def list_mixers():
    """List known mixers."""
    from api.services.data_access import DataAccess

    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    mixers = data.get_mixers(chain_code=chain)

    return jsonify({
        "mixers": [
            {"address": m.address, "chain": m.chain_code, "protocol": m.protocol, "name": m.name, "pool_size": m.pool_size}
            for m in mixers
        ],
        "total": len(mixers)
    }), 200


@label_bp.route("/bridges", methods=['GET'])
def list_bridges():
    """List known bridges."""
    from api.services.data_access import DataAccess

    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    bridges = data.get_bridges(chain_code=chain)

    return jsonify({
        "bridges": [
            {"address": b.address, "chain": b.chain_code, "protocol": b.protocol, "name": b.name, "direction": b.direction}
            for b in bridges
        ],
        "total": len(bridges)
    }), 200


@label_bp.route("/check/<address>", methods=['GET'])
def check_address(address):
    """Check address risk profile using DB data."""
    from api.services.data_access import DataAccess

    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    is_mixer = data.is_mixer(address, chain_code=chain)
    is_bridge = data.is_bridge(address, chain_code=chain)
    tags = data.get_wallet_tags(address, chain_code=chain)
    risk_level = _get_risk_level(is_mixer, is_bridge, tags)

    return jsonify({
        "address": address,
        "chain": chain,
        "is_mixer": is_mixer,
        "is_bridge": is_bridge,
        "risk_level": risk_level,
        "tags": [
            {
                "tag": t.tag, "chain": t.chain_code, "source": t.source,
                "confidence": t.confidence,
                "category": t.category.name if t.category else None,
                "risk_level": t.category.risk_level if t.category else None
            }
            for t in tags
        ]
    }), 200
