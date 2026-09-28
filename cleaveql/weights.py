import json
import os

class WeightManager:
    def __init__(self, directory="attention_weights"):
        self.directory = directory
        if not os.path.exists(directory):
            os.makedirs(directory)

    def save_weights(self, model_name, weights):
        path = os.path.join(self.directory, f"{model_name}.json")
        with open(path, "w") as f:
            json.dump(weights, f)

    def load_weights(self, model_name):
        path = os.path.join(self.directory, f"{model_name}.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {}
