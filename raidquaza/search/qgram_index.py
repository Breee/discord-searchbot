import re
import numpy as np
import csv
from collections import Counter
from abc import ABC, abstractmethod
from geofence.geofencehelper import GeofenceHelper
from config.Configuration import Configuration
from search.enums import SCORING_TYPE, RECORD_TYPE


def get_qgrams(str, q):
    """ Returns all q-grams for str.
        >>> get_qgrams("bananarana", 3)
        ['$$b', '$ba', 'ban', 'ana', 'nan', 'ana', 'nar', 'ara', 'ran', 'ana', 'na$', 'a$$']
        >>> get_qgrams("b", 3)
        ['$$b', '$b$', 'b$$']
        >>> get_qgrams("ba", 4)
        ['$$$b', '$$ba', '$ba$', 'ba$$', 'a$$$']
        >>> get_qgrams("banana", 2)
        ['$b', 'ba', 'an', 'na', 'an', 'na', 'a$']
        """
    str = "$" * (q - 1) + str + "$" * (q - 1)
    qgrams = []
    for i in range(0, len(str) - q + 1):
        qgram = str[i:i + q]
        qgrams.append(qgram)
    return qgrams


def merge(lists):
    """ Merge the inverted lists and return a list of tuples (record id,
        count). Alternatively, you can also return a dictionary from record ids
        to counts.
        >>> merge([[1, 2, 3], [2, 3, 4], [3, 4, 5]])
        [(1, 1), (2, 2), (3, 3), (4, 2), (5, 1)]
        >>> merge([[1, 3, 4, 6, 7], [1, 3, 4, 5, 6, 7, 10]])
        [(1, 2), (3, 2), (4, 2), (6, 2), (7, 2), (5, 1), (10, 1)]
        >>> merge([[], []])
        []
        >>> merge([[1], [2], [3]])
        [(1, 1), (2, 1), (3, 1)]
        >>> merge([[1], [2, 4], []])
        [(1, 1), (2, 1), (4, 1)]
        """
    record_counter = Counter()
    for l in lists:
        record_counter.update(l)
    return list(record_counter.items())


def compute_ped(prefix, str, delta):
    """ Check wether the prefix edit distance between prefix
        and str is at most delta

        >>> compute_ped("foo", "foo", 0)
        0
        >>> compute_ped("foo", "foo", 10)
        0
        >>> compute_ped("foo", "foot", 10)
        0
        >>> compute_ped("foot", "foo", 1)
        1
        >>> compute_ped("foo", "fotbal", 1)
        1
        >>> compute_ped("foo", "bar", 3)
        3
        >>> compute_ped("perf", "perv", 1)
        1
        >>> compute_ped("perv", "perf", 1)
        1
        >>> compute_ped("perf", "peff", 1)
        1
        >>> compute_ped("foot", "foo", 0)
        1
        >>> compute_ped("foo", "fotbal", 0)
        1
        >>> compute_ped("foo", "bar", 2)
        3
        >>> compute_ped("uniwer", "university", 6)
        1
        >>> compute_ped("munchen", "münchen", 1)
        1
        """
    # Account for epsilon
    n = len(prefix) + 1
    m = min(len(prefix) + delta + 1, len(str) + 1)
    # Initialize matrix
    matrix = [[0 for _ in range(m)] for _ in range(n)]
    for j in range(1, n):
        matrix[j][0] = j
    for j in range(1, m):
        matrix[0][j] = j
    # Dynamic programming.
    for i in range(1, n):
        for j in range(1, m):
            repl = matrix[i - 1][j - 1] + 1
            if prefix[i - 1] == str[j - 1]:
                repl = matrix[i - 1][j - 1]
            matrix[i][j] = min(min(repl, matrix[i][j - 1] + 1),
                               matrix[i - 1][j] + 1)
    ped = min(matrix[n - 1])
    return ped


def levenshtein(seq1, seq2):
    match = 0
    mismatch = 1
    gap_penalty = 1
    size_x = len(seq1) + 1
    size_y = len(seq2) + 1
    matrix = np.zeros((size_x, size_y))
    for x in range(size_x):
        matrix[x, 0] = x
    for y in range(size_y):
        matrix[0, y] = y

    for x in range(1, size_x):
        for y in range(1, size_y):
            if seq1[x - 1] == seq2[y - 1]:
                matrix[x, y] = min(
                        matrix[x - 1, y] + gap_penalty,
                        matrix[x - 1, y - 1] + match,
                        matrix[x, y - 1] + gap_penalty
                )
            else:
                matrix[x, y] = min(
                        matrix[x - 1, y] + gap_penalty,
                        matrix[x - 1, y - 1] + mismatch,
                        matrix[x, y - 1] + gap_penalty
                )
    return (matrix[size_x - 1, size_y - 1])


def needleman_wunsch_scoring(seq1, seq2):
    match = -1
    mismatch = 1
    gap_penalty = 1
    gap_opening = 3
    gap_opened = False
    size_x = len(seq1) + 1
    size_y = len(seq2) + 1
    matrix = np.zeros((size_x, size_y))
    for x in range(size_x):
        matrix[x, 0] = x
    for y in range(size_y):
        matrix[0, y] = y

    for x in range(1, size_x):
        for y in range(1, size_y):
            if seq1[x - 1] == seq2[y - 1]:
                matrix[x, y] = min(
                        matrix[x - 1, y] + gap_penalty,
                        matrix[x - 1, y - 1] + match,
                        matrix[x, y - 1] + gap_penalty
                )
            else:
                matrix[x, y] = min(
                        matrix[x - 1, y] + gap_penalty,
                        matrix[x - 1, y - 1] + mismatch,
                        matrix[x, y - 1] + gap_penalty
                )
            if (matrix[x, y] == matrix[x - 1, y] + gap_penalty or matrix[x, y - 1] + gap_penalty) and not gap_opened:
                matrix[x, y] += gap_opening
                gap_opened = True
            else:
                gap_opened = False

    return (matrix[size_x - 1, size_y - 1])


def affine_gap_scoring(seq1, seq2):
    match = -3
    mismatch = 1
    gap_penalty = 0.5
    gap_opening = 3
    gap_opened = False
    size_x = len(seq1) + 1
    size_y = len(seq2) + 1
    matrix = np.zeros((size_x, size_y))
    for x in range(size_x):
        matrix[x, 0] = x
    for y in range(size_y):
        matrix[0, y] = y

    for x in range(1, size_x):
        for y in range(1, size_y):
            if seq1[x - 1] == seq2[y - 1]:
                matrix[x, y] = min(
                        matrix[x - 1, y] + gap_penalty,
                        matrix[x - 1, y - 1] + match,
                        matrix[x, y - 1] + gap_penalty
                )
            else:
                matrix[x, y] = min(
                        matrix[x - 1, y] + gap_penalty,
                        matrix[x - 1, y - 1] + mismatch,
                        matrix[x, y - 1] + gap_penalty
                )
            if (matrix[x, y] == matrix[x - 1, y] + gap_penalty or matrix[x, y - 1] + gap_penalty):
                if not gap_opened:
                    matrix[x, y] += gap_opening
                    gap_opened = True
            else:
                gap_opened = False
    return (matrix[size_x - 1, size_y - 1])


class QgramIndex(ABC):
    """ A q-gram index, adapted from the inverted index code from Lecture 1.
    """

    def __init__(self, q):
        """ Create an empty q-gram index for given q (size of the q-grams). """
        self.inverted_lists = dict()
        self.q = q
        self.vocab = dict()
        self.longitude = []
        self.latitude = []
        self.types = []
        self.scoring_method = SCORING_TYPE.AFFINE_GAPS

    @abstractmethod
    def build_from_file(self, file_name):
        """ Build index for text in given file, one record per line. """
        pass

    @abstractmethod
    def build_from_lists(self, input, geofence=None):
        """ Build index of point of interest, from a list which contains tuples of the form (name,lat,lon,type)"""
        pass

    @abstractmethod
    def get_posting_list(self, qgram):
        """ Returns the posting list for the given word if it exists else an
        empty list.
        """
        pass

    @abstractmethod
    def find_matches(self, query, delta, k=5, use_qindex=True):
        pass


class PointOfInterestQgramIndex(QgramIndex):
    """ A q-gram index for Point of interests.
    A point of interest is a tuple (name,latitude,longitude,type)
    types are Arena,Pokestop.
    """

    def __init__(self, q, use_geofences, channel_to_geofences):
        """ Create an empty q-gram index for given q (size of the q-grams). """
        super().__init__(q)
        self.use_geofences = use_geofences
        self.channel_to_geofence_helper = dict()
        if self.use_geofences:
            for channel_id, geofence in channel_to_geofences.items():
                self.channel_to_geofence_helper[channel_id] = GeofenceHelper(geofence)

    def build_from_file(self, file_name):
        """ Build index for text in given file, one record per line. """

        with open(file_name, 'r', encoding='utf-8', errors='replace') as file:
            record_id = 0
            reader = csv.reader(file, delimiter=',', quotechar='|')
            # skip header
            next(reader, None)
            for row in reader:
                # first tab is the name/record
                record = row[0].strip()
                self.vocab[record_id] = record
                # the if/else contructs are necessary because the file lines
                # dont got always 3 entries
                # second tab, longitude
                if (len(row) > 1):
                    self.latitude.append(row[1].strip())
                else:
                    self.latitude.append(None)
                # third tab, latitude
                if (len(row) > 2):
                    self.longitude.append(row[2].strip())
                else:
                    self.longitude.append(None)

                # fourth tab, type
                if (len(row) > 3):
                    if row[3].strip() == 'Gym':
                        self.types.append(RECORD_TYPE.GYM)
                    elif row[3].strip() == 'Pokestop':
                        self.types.append(RECORD_TYPE.POKESTOP)
                    else:
                        self.types.append(RECORD_TYPE.UNKNOWN)
                else:
                    self.types.append(None)

                # on the fly calc qgrams
                word = re.sub("[ \W+\n]", "", record).lower()
                qgrams = get_qgrams(word, self.q)
                for qgram in qgrams:
                    if qgram not in self.inverted_lists:
                        self.inverted_lists[qgram] = list()
                    self.inverted_lists[qgram].append(record_id)
                record_id += 1

    def build_from_lists(self, input):
        """ Build index of point of interest, from a list which contains tuples of the form (name,lat,lon,type)"""
        record_id = 0
        for row in input:
            # first tab is the name/record
            record = row[0].strip()
            self.vocab[record_id] = record
            # the if/else contructs are necessary because the file lines
            # dont got always 3 entries
            # second tab, longitude
            if (len(row) > 1):
                self.longitude.append(row[2])
            else:
                self.longitude.append(None)
            # third tab, latitude
            if (len(row) > 2):
                self.latitude.append(row[1])
            else:
                self.latitude.append(None)

            # fourth tab, type
            if (len(row) > 3):
                record_type = row[3]
                if record_type == RECORD_TYPE.GYM or record_type == RECORD_TYPE.POKESTOP:
                    self.types.append(record_type)
                else:
                    self.types.append(RECORD_TYPE.UNKNOWN)
            else:
                self.types.append(RECORD_TYPE.UNKNOWN)

            # on the fly calc qgrams
            word = re.sub("[ \W+\n]", "", record).lower()
            self.vocab[record_id] = record
            qgrams = get_qgrams(word, self.q)
            for qgram in qgrams:
                if qgram not in self.inverted_lists:
                    self.inverted_lists[qgram] = list()
                self.inverted_lists[qgram].append(record_id)
            record_id += 1

    def get_posting_list(self, qgram):
        """ Returns the posting list for the given word if it exists else an
        empty list.
        """
        return self.inverted_lists.get(qgram, [])

    def get_score(self, query, word):
        if self.scoring_method == SCORING_TYPE.LEVENSHTEIN:
            ed = levenshtein(query, word)
        elif self.scoring_method == SCORING_TYPE.NEEDLEMAN_WUNSCH:
            ed = needleman_wunsch_scoring(query, word)
        elif self.scoring_method == SCORING_TYPE.AFFINE_GAPS:
            ed = affine_gap_scoring(query, word)
        else:
            raise NotImplementedError(f'scoring method {self.scoring_method} not implemented.')
        return ed

    def find_matches(self, query, delta, k=5, use_qindex=True, channel_id=None):
        """ Find the top-k matches
            """
        result_words = []
        # We use the q-gram index to pre-filter.
        if use_qindex:
            qgrams = get_qgrams(query, self.q)
            record_lists = [self.get_posting_list(qgram) for qgram in qgrams]
            merged_lists = merge(record_lists)
            threshold = (len(query) + self.q - 1) / 4
            for record_id, count in merged_lists:
                record = self.vocab[record_id]
                word = re.sub("[ \W+\n]", "", record).lower()
                if count >= int(threshold):
                    ed = self.get_score(query, word)
                    longitude = self.longitude[record_id]
                    latitude = self.latitude[record_id]
                    type = self.types[record_id]
                    if self.use_geofences and channel_id and channel_id in self.channel_to_geofence_helper:
                        geofence_helper = self.channel_to_geofence_helper[channel_id]
                        # check if point is in geofence
                        if geofence_helper.is_in_any_geofence(latitude, longitude):
                            result_words.append((record, (latitude, longitude), type, ed))
                    else:
                        result_words.append((record, (latitude, longitude), type, ed))
        result = sorted(result_words, key=lambda x: x[3], reverse=False)[:k]
        return result


class QuestQgramIndex(QgramIndex):
    """ A q-gram index for Quests.
    """

    def __init__(self, q):
        """ Create an empty q-gram index for given q (size of the q-grams). """
        super().__init__(q)

    def build_from_file(self, file_name):
        """ Build index for text in given file, one record per line. """
        raise NotImplementedError("not implemented for this index.")

    def build_from_lists(self, input):
        """ Build index of point of interest, from a list which contains tuples of the form (name,lat,lon,type)"""
        raise NotImplementedError("not implemented for this index.")

    def get_posting_list(self, qgram):
        """ Returns the posting list for the given word if it exists else an
        empty list.
        """
        raise NotImplementedError("not implemented for this index.")

    def find_matches(self, query, delta, k=5, use_qindex=True):
        """ Find the top-k matches
            """
        raise NotImplementedError("not implemented for this index.")