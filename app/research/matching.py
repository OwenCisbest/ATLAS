"""Heuristic grades, not calibrated probabilities; suggestions never merge identities."""
import json


def suggest(store, investigation_id: str) -> int:
    data = store.snapshot(investigation_id)
    count = 0
    existing = {(r['source_id'], r['target_id'], r['label']) for r in data['relationships']}
    for i, left in enumerate(data['evidence']):
        for right in data['evidence'][i + 1:]:
            score, explanation = 0, ''
            if left['source_url'].rstrip('/') == right['source_url'].rstrip('/'):
                score, explanation = 75, 'Both records cite the identical source URL. This links records, not verified real-world identities.'
            else:
                a, b = json.loads(left['details']), json.loads(right['details'])
                if a.get('username') and a.get('username', '').casefold() == b.get('username', '').casefold():
                    score, explanation = 25, 'Same public username only. Independent evidence is required before confirming identity.'
            label = 'potential same entity'
            if score and (left['id'], right['id'], label) not in existing:
                store.relate(investigation_id, left['id'], right['id'], left['id'], label, explanation, score)
                count += 1
    return count
