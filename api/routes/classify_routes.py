"""Wallet classification (ML scoring) endpoints."""

from flask import Blueprint, request, jsonify, g
from sqlalchemy import func

classify_bp = Blueprint('classify', __name__)


@classify_bp.route("/wallets/<address>/classify", methods=['GET'])
def classify_wallet(address):
    """Classify a wallet using ML and heuristics."""
    from api.services.wallet_classifier import get_wallet_classifier

    chain = request.args.get('chain', 'POL').upper()

    try:
        classifier = get_wallet_classifier()
        result = classifier.classify(address, chain, save_result=True)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@classify_bp.route("/wallets/<address>/similar", methods=['GET'])
def find_similar_wallets(address):
    """Find wallets with similar behavior patterns."""
    from api.services.wallet_classifier import get_wallet_classifier

    chain = request.args.get('chain', 'POL').upper()
    limit = int(request.args.get('limit', 10))

    try:
        classifier = get_wallet_classifier()
        similar = classifier.find_similar_wallets(address, chain, limit)
        return jsonify({"address": address, "chain": chain, "similar_wallets": similar}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@classify_bp.route("/wallets/batch-classify", methods=['POST'])
def batch_classify_wallets():
    """Classify multiple wallets at once."""
    from api.services.wallet_classifier import get_wallet_classifier

    data = request.get_json()
    addresses = data.get('addresses', [])
    chain = data.get('chain', 'POL').upper()

    if not addresses:
        return jsonify({"error": "No addresses provided"}), 400
    if len(addresses) > 50:
        return jsonify({"error": "Maximum 50 addresses per request"}), 400

    try:
        classifier = get_wallet_classifier()
        results = classifier.batch_classify(addresses, chain)
        return jsonify({"chain": chain, "results": results}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@classify_bp.route("/scores/stats", methods=['GET'])
def get_wallet_scores_stats():
    """Get statistics about wallet classifications."""
    from api.application.erc20models import WalletScore, CHAIN_ID_TO_TRIGRAM

    try:
        session = g.db_session

        type_counts = session.query(
            WalletScore.predicted_type, func.count(WalletScore.id)
        ).group_by(WalletScore.predicted_type).all()

        anomaly_count = session.query(WalletScore).filter_by(is_anomaly=True).count()
        total_scored = session.query(WalletScore).count()

        return jsonify({
            "total_scored": total_scored,
            "anomalies": anomaly_count,
            "by_type": {ptype or 'unknown': count for ptype, count in type_counts}
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
