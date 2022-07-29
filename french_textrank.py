from collections.abc import Iterator, Callable
from typing import TypeAlias
import heapq
from operator import itemgetter
import numpy as np
import numpy.typing as npt
from scipy.spatial import distance # type: ignore
from sentence_transformers import SentenceTransformer # type: ignore
from spacy.lang.fr import French

# pylint: disable=invalid-name

class FrenchTextRank():

    IndexedText: TypeAlias = tuple[int, str]
    IndexedTexts: TypeAlias = Iterator[IndexedText]
    Ranking: TypeAlias = npt.NDArray[np.float64]
    RankedText: TypeAlias = tuple[IndexedText, Ranking]

    nlp = French()
    nlp.add_pipe("sentencizer")
    sbert = SentenceTransformer('Sahajtomar/french_semantic')

    # def __init__(self, n_sentences, damping_factor=0.8):
    def __init__(self, damping_factor=0.8):

        # self.n_sentences = n_sentences
        self.damping_factor = damping_factor

    @staticmethod
    def sentencizer(text: str) -> list[str]:
        return list(map(str, FrenchTextRank.nlp(text).sents))

    def sim(self, u, v):
        return abs(1 - distance.cdist(u, v, 'cosine'))

    def cosine(self, u, v):
        return abs(1 - distance.cosine(u, v))

    def rescale(self, a):
        maximum = np.max(a)
        minimum = np.min(a)

        return (a - minimum) / (maximum - minimum)

    def normalize(self, matrix):

        for row in matrix:
            row_sum = np.sum(row)
            if row_sum != 0:
                row /= row_sum

        return matrix

    def textrank(self, texts_embeddings, similarity_threshold=0.8):

        matrix = self.sim(texts_embeddings, texts_embeddings)
        np.fill_diagonal(matrix, 0)
        matrix[matrix < similarity_threshold] = 0

        matrix = self.normalize(matrix)

        scaled_matrix = self.damping_factor * matrix
        scaled_matrix = self.normalize(scaled_matrix)
        # scaled_matrix = rescale(scaled_matrix)

        ranks = np.ones((len(matrix), 1)) / len(matrix)
        iterations = 80
        for _ in range(iterations):
            ranks = scaled_matrix.T.dot(ranks)

        return ranks

    def get_sbert_embedding(self, text):

        if isinstance(text, (list, tuple)):
            return self.sbert.encode(text)

        return self.sbert.encode([text])

    def select_top_k_texts_preserving_order(self, texts, ranking, k) -> list[str]:

        indexed_texts: FrenchTextRank.IndexedTexts
        top_ranked_texts: list[FrenchTextRank.RankedText]

        indexed_texts = enumerate(texts)
        top_ranked_texts = heapq.nlargest(k, zip(indexed_texts, ranking), key=itemgetter(1))

        top_texts: Iterator[FrenchTextRank.IndexedText]
        top_texts = (indexed_text for indexed_text, _ in top_ranked_texts)

        top_texts_in_preserved_order = [text for _, text in sorted(top_texts, key=itemgetter(0))]

        return top_texts_in_preserved_order

    def get_sentences(self, text, sent_pred):

        paragraphs = text.split('\n')
        sentences = []
        for paragraph in paragraphs:
            sentences += self.sentencizer(paragraph)
        sentences = [s for s in sentences
                     if s and not s.isspace()
                        and sent_pred(s)]

        return sentences


    def summarize(
        self, doc: str,
        n_sentences: int,
        sent_pred: Callable[[str], bool]=lambda _: True):

        sentences = self.get_sentences(doc, sent_pred)

        embedded_sentences = self.get_sbert_embedding(sentences)

        ranks = self.textrank(embedded_sentences)

        top_sentences = self.select_top_k_texts_preserving_order(
            sentences, ranks, n_sentences)

        summary = '\n'.join(top_sentences)

        return summary