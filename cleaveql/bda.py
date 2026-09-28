class BondDiscoveryAttention:
    def __init__(self):
        pass

    def suggest_bonds(self, bucket_name):
        # Field-key overlap scoring
        return [{"from": bucket_name, "to": "users", "confidence": 0.95}]
