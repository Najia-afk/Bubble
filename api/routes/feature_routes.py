"""Feature engineering endpoints."""

from flask import Blueprint, request, jsonify, g

feature_bp = Blueprint('features', __name__)


@feature_bp.route("/features/<address>", methods=['GET'])
def get_wallet_features(address):
    """Extract features for a wallet address."""
    from api.services.feature_engineer import WalletFeatureEngineer

    chain = request.args.get('chain', 'ETH').upper()
    lookback_days = int(request.args.get('lookback_days', 90))

    try:
        engineer = WalletFeatureEngineer(session=g.db_session)
        features = engineer.extract_features(address=address, chain=chain, lookback_days=lookback_days)

        return jsonify({
            "address": address, "chain": chain,
            "lookback_days": lookback_days,
            "feature_count": len(features),
            "features": features
        }), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@feature_bp.route("/features/names", methods=['GET'])
def get_feature_names():
    """Get list of all feature names with categories."""
    from api.services.feature_engineer import WalletFeatureEngineer

    engineer = WalletFeatureEngineer()

    return jsonify({
        "feature_names": engineer.get_feature_names(),
        "feature_categories": engineer.get_feature_importance_groups(),
        "total_features": len(engineer.get_feature_names())
    }), 200
