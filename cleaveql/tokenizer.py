"""Word-piece tokenizer for Query Understanding Attention (QUA)."""
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple


class WordPieceTokenizer:
    """Byte-pair-encoding-style word-piece tokenizer.
    
    Builds a vocabulary from training data by iteratively merging
    the most frequent adjacent token pairs.
    """

    UNK_TOKEN = "[UNK]"
    PAD_TOKEN = "[PAD]"
    CLS_TOKEN = "[CLS]"
    SEP_TOKEN = "[SEP]"
    SPECIAL_TOKENS = [PAD_TOKEN, UNK_TOKEN, CLS_TOKEN, SEP_TOKEN]

    def __init__(self, vocab_size: int = 8000):
        self.vocab_size = vocab_size
        self.token_to_id: Dict[str, int] = {}
        self.id_to_token: Dict[int, str] = {}
        self._built = False

    def build_vocab(self, texts: List[str]):
        """Build vocabulary from training texts using BPE-style merging."""
        # Step 1: Pre-tokenize and split into characters
        word_freqs: Counter = Counter()
        for text in texts:
            words = self._pre_tokenize(text)
            for word in words:
                word_freqs[word] += 1

        # Initialize vocab with all characters + special tokens
        char_set = set()
        for word in word_freqs:
            for ch in word:
                char_set.add(ch)

        vocab = list(self.SPECIAL_TOKENS) + sorted(char_set)

        # Step 2: Build word splits (each word -> list of chars, with ## prefix for continuation)
        splits = {}
        for word in word_freqs:
            chars = list(word)
            splits[word] = [chars[0]] + ["##" + c for c in chars[1:]]

        # Step 3: Iteratively merge most frequent pairs
        while len(vocab) < self.vocab_size:
            pair_freqs: Counter = Counter()
            for word, freq in word_freqs.items():
                word_splits = splits[word]
                for i in range(len(word_splits) - 1):
                    pair = (word_splits[i], word_splits[i + 1])
                    pair_freqs[pair] += freq

            if not pair_freqs:
                break

            best_pair = pair_freqs.most_common(1)[0][0]
            merged = best_pair[0] + best_pair[1].replace("##", "")
            if best_pair[1].startswith("##"):
                merged = best_pair[0] + best_pair[1][2:]
                if best_pair[0].startswith("##"):
                    merged = "##" + merged[2:] if not merged.startswith("##") else merged

            # Merge in all words
            new_splits = {}
            for word, word_splits in splits.items():
                new_word_splits = []
                i = 0
                while i < len(word_splits):
                    if i < len(word_splits) - 1 and (word_splits[i], word_splits[i + 1]) == best_pair:
                        new_tok = word_splits[i] + word_splits[i + 1].replace("##", "")
                        new_word_splits.append(new_tok)
                        i += 2
                    else:
                        new_word_splits.append(word_splits[i])
                        i += 1
                new_splits[word] = new_word_splits
            splits = new_splits

            if merged not in vocab:
                vocab.append(merged)

        # Build lookup dicts
        self.token_to_id = {tok: idx for idx, tok in enumerate(vocab)}
        self.id_to_token = {idx: tok for idx, tok in enumerate(vocab)}
        self._built = True

    def encode(self, text: str) -> List[int]:
        """Encode text to token IDs."""
        if not self._built:
            raise RuntimeError("Tokenizer vocabulary not built. Call build_vocab() first.")

        ids = [self.token_to_id[self.CLS_TOKEN]]
        words = self._pre_tokenize(text)

        for word in words:
            sub_tokens = self._tokenize_word(word)
            for tok in sub_tokens:
                ids.append(self.token_to_id.get(tok, self.token_to_id[self.UNK_TOKEN]))

        ids.append(self.token_to_id[self.SEP_TOKEN])
        return ids

    def decode(self, ids: List[int]) -> str:
        """Decode token IDs back to text."""
        tokens = []
        for tok_id in ids:
            tok = self.id_to_token.get(tok_id, self.UNK_TOKEN)
            if tok in self.SPECIAL_TOKENS:
                continue
            if tok.startswith("##"):
                tokens.append(tok[2:])
            else:
                tokens.append(" " + tok if tokens else tok)
        return "".join(tokens)

    def _pre_tokenize(self, text: str) -> List[str]:
        """Split text into words on whitespace and punctuation."""
        return re.findall(r'\w+|[^\w\s]', text.lower())

    def _tokenize_word(self, word: str) -> List[str]:
        """Tokenize a single word into subword pieces."""
        if word in self.token_to_id:
            return [word]

        tokens = []
        start = 0
        while start < len(word):
            end = len(word)
            found = None
            while start < end:
                substr = word[start:end]
                if start > 0:
                    substr = "##" + substr
                if substr in self.token_to_id:
                    found = substr
                    break
                end -= 1
            if found is None:
                tokens.append(self.UNK_TOKEN)
                start += 1
            else:
                tokens.append(found)
                start = end
        return tokens

    @property
    def vocab(self) -> Dict[str, int]:
        return dict(self.token_to_id)
