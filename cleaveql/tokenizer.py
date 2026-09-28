class WordPieceTokenizer:
    def __init__(self, vocab=None):
        self.vocab = vocab or {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3}
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def encode(self, text):
        # Extremely simplified for prototype
        tokens = text.lower().split()
        return [self.vocab.get(t, self.vocab["[UNK]"]) for t in tokens]

    def decode(self, token_ids):
        return " ".join([self.inv_vocab.get(t, "[UNK]") for t in token_ids])

    def train(self, texts):
        # Build naive vocab
        idx = len(self.vocab)
        for text in texts:
            for token in text.lower().split():
                if token not in self.vocab:
                    self.vocab[token] = idx
                    self.inv_vocab[idx] = token
                    idx += 1
