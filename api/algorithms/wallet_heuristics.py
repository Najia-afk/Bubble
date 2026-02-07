"""
Wallet Classification Heuristics — Pure rule-based classification.

Takes feature dicts as input, returns predicted types & confidence.
No DB access, no ML models — just rules.
"""
from typing import Dict, Tuple


# ─── Thresholds ──────────────────────────────────────────────────────────────

EXCHANGE_THRESHOLDS = {
    'min_unique_counterparties': 100,
    'min_tx_count': 200,
    'in_out_ratio_range': (0.7, 1.3),
}

MIXER_THRESHOLDS = {
    'min_unique_senders': 10,
    'min_unique_recipients': 10,
    'min_tx_count': 50,
}

BRIDGE_THRESHOLDS = {
    'min_tx_count': 20,
    'max_counterparties': 20,
    'balance_ratio_min': 0.8,  # in/out volume balance
}

WHALE_THRESHOLDS = {
    'min_total_volume': 100_000,
}

BOT_THRESHOLDS = {
    'min_tx_count': 100,
    'max_counterparties': 10,
}


def classify_from_transfer_stats(stats: Dict) -> Dict:
    """
    Classify a wallet from its InvestigationTransfer statistics.
    
    Args:
        stats: Dict with keys from investigation_queries.get_address_transfer_stats()
               {out_count, out_total, unique_recipients, in_count, in_total, unique_senders}
               
    Returns:
        {predicted_type, confidence, features}
    """
    out_count = stats.get('out_count', 0)
    out_total = stats.get('out_total', 0)
    unique_recipients = stats.get('unique_recipients', 0)
    in_count = stats.get('in_count', 0)
    in_total = stats.get('in_total', 0)
    unique_senders = stats.get('unique_senders', 0)

    total_txs = in_count + out_count
    total_counterparties = unique_senders + unique_recipients

    if total_txs == 0:
        return {'predicted_type': 'unknown', 'confidence': 0.0, 'features': stats}

    features = {**stats, 'total_txs': total_txs, 'total_counterparties': total_counterparties}

    predicted_type = 'normal'
    confidence = 0.3

    # Exchange: many counterparties, high volume both ways
    if (total_counterparties >= EXCHANGE_THRESHOLDS['min_unique_counterparties']
            and total_txs >= EXCHANGE_THRESHOLDS['min_tx_count']):
        predicted_type = 'exchange'
        confidence = min(0.9, 0.5 + total_counterparties / 1000)

    # Mixer: receives from many, sends to many, moderate volume
    elif (unique_senders >= MIXER_THRESHOLDS['min_unique_senders']
          and unique_recipients >= MIXER_THRESHOLDS['min_unique_recipients']
          and total_txs >= MIXER_THRESHOLDS['min_tx_count']):
        predicted_type = 'mixer'
        confidence = 0.6

    # Bridge: balanced in/out, few counterparties
    elif total_txs >= BRIDGE_THRESHOLDS['min_tx_count'] and total_counterparties < BRIDGE_THRESHOLDS['max_counterparties']:
        max_vol = max(in_total, out_total)
        ratio = min(in_total, out_total) / max_vol if max_vol > 0 else 0
        if ratio > BRIDGE_THRESHOLDS['balance_ratio_min']:
            predicted_type = 'bridge'
            confidence = 0.5

    # Whale: very high volume
    elif out_total > WHALE_THRESHOLDS['min_total_volume'] or in_total > WHALE_THRESHOLDS['min_total_volume']:
        predicted_type = 'whale'
        confidence = 0.6

    # Bot: many txs, few counterparties
    elif total_txs >= BOT_THRESHOLDS['min_tx_count'] and total_counterparties < BOT_THRESHOLDS['max_counterparties']:
        predicted_type = 'bot'
        confidence = 0.5

    # DeFi: moderate activity
    elif total_txs >= 20:
        predicted_type = 'defi'
        confidence = 0.4

    return {'predicted_type': predicted_type, 'confidence': confidence, 'features': features}


def classify_from_token_features(features: Dict) -> Tuple[str, float]:
    """
    Classify from per-token transfer table features 
    (wallet_queries.get_token_transfer_features output).
    
    Returns (predicted_type, confidence).
    """
    tx_count = features.get('tx_count', 0)
    unique_cp = features.get('unique_counterparties', 0)
    avg_value = features.get('avg_tx_value', 0)
    max_value = features.get('max_tx_value', 0)
    total_volume = features.get('total_volume', 0)
    in_out_ratio = features.get('in_out_ratio', 1.0)

    scores = {}

    # Exchange
    if unique_cp >= 100 and tx_count >= 500:
        if 0.8 <= in_out_ratio <= 1.2:
            scores['exchange'] = 0.8
        else:
            scores['exchange'] = 0.5

    # Bridge
    if tx_count >= 50 and avg_value >= 1000:
        if 0.9 <= in_out_ratio <= 1.1:
            scores['bridge'] = 0.75
        else:
            scores['bridge'] = 0.4

    # Whale
    if total_volume >= 100_000 or max_value >= 10_000:
        scores['whale'] = 0.7

    # Bot
    if tx_count >= 1000:
        cp_ratio = unique_cp / tx_count if tx_count > 0 else 1
        if cp_ratio <= 0.1:
            scores['bot'] = 0.65

    # DeFi
    if 10 <= tx_count <= 500 and avg_value >= 100:
        scores['defi'] = 0.5

    if not scores:
        scores['normal'] = 0.6

    best_type = max(scores, key=scores.get)
    return best_type, scores[best_type]
