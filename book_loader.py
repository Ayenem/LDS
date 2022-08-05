from __future__ import annotations
import warnings
from pathlib import Path
import re
import json
from collections.abc import Iterator, Callable
from typing import ClassVar, TypeAlias, TypedDict
from typing_extensions import Required

import funcy as fy
from funcy_chain import IterChain, Chain
from docx import Document
from simplify_docx import simplify
import deal

import my_utils as ut

warnings.filterwarnings("ignore", message="Skipping unexpected tag")

# TODO: This function should be @cache'd
# TODO: Write a read_chapters_contract with @deal.chain
@deal.safe
@deal.has('read')
@deal.pre(lambda _: _.first >= 0)
@deal.pre(lambda _: _.last >= _.first)
@deal.ensure(lambda _: len(_.result) == _.last - _.first + 1)
def read_chapters(first=0, last: int | None=None) -> list[str]:

    with open('parameters.json', 'r', encoding="utf-8") as json_file:
        params = json.load(json_file)

    book = BookLoader(**params)

    chapters = book.chapters[first:
                             None if last is None
                             else last + 1]
    # Slicing chapter[1: ] because chapter[0] is pre-chapter 1
    return ['\n'.join(paragraph for paragraph in chapter[1: ])
            for chapter in chapters]

@deal.pure
def join_bisections() -> Callable[[str], Iterator[str]]:

    bisection = BookLoader.re_compile_unicode(r"(\w+)-\s(\w+)")
    join_bisection = fy.partial(bisection.sub, r"\1\2")

    return lambda text: map(join_bisection, text)

@deal.pure
def table_to_text() -> Callable[[list[dict[str, list[dict]]]], str]:

    values_of = fy.partial(fy.pluck, "VALUE")

    @deal.pre(lambda table: all(e["TYPE"] == "table-row" for e in table))
    def _table_to_text(table):
        return ' '.join(
            text
            for row in values_of(table)
            for cell in values_of(row)
            for content in values_of(cell)
            for text in values_of(content))

    return _table_to_text

@deal.has('read')
@deal.raises(ValueError)
@deal.pre(lambda doc_path: doc_path.exists())
def read_paragraphs(doc_path: Path) -> Iterator[str]:

    _simple_docx = simplify(Document(doc_path),
                            {"include-paragraph-indent": False,
                            "include-paragraph-numbering": False})
    simple_docx = ut.one_expected(_simple_docx["VALUE"])["VALUE"]

    return (IterChain(simple_docx)
                .pluck("VALUE")
                .without("[w:sdt]")
                .map(ut.lwhere_not_(TYPE="CT_Empty"))
                .compact()
                .map(fy.iffy(pred=lambda p: p[0]["TYPE"] == "text",
                             action=lambda p: ut.one_expected(p)["VALUE"],
                             default=table_to_text()))
            ).value

Pattern:        TypeAlias = re.Pattern[str]
Marker:         TypeAlias = Pattern | str
MarkersPair:    TypeAlias = list[str | Pattern]
PatternsPair:   TypeAlias = list[Pattern]

class Markers(TypedDict, total=False):

    chapter:        Required[Marker]
    slice:          MarkersPair
    header:         Marker
    references:     Marker
    undesirables:   Marker
    na_span:        MarkersPair

class BookLoader:

    re_compile_unicode: ClassVar[Callable] = fy.partial(re.compile, flags=re.UNICODE)
    _match_anything:    ClassVar[Pattern] = re.compile(".*", flags=re.DOTALL)
    _match_nothing:     ClassVar[Pattern] = re.compile("a^")

    chapter:        Pattern
    slice:          PatternsPair = [_match_anything, _match_anything]
    header:         Pattern = _match_nothing
    references:     Pattern = _match_nothing
    undesirables:   Pattern = _match_nothing
    na_span:        PatternsPair = [_match_nothing, _match_nothing]

    chapters:       list[list[str]]

    @deal.safe
    def __init__(self, doc_path: str, markers: Markers):

        _compiled_markers = fy.walk_values(
            fy.iffy(pred=fy.is_list,
                    action=ut.lmap_(self.re_compile_unicode),
                    default=self.re_compile_unicode),
            markers)
        self.__dict__.update(_compiled_markers)

        _paragraphs = self._etl_paragraphs(doc_path)
        self.chapters = (Chain(_paragraphs)
                            .group_by(self._chapter_indexer())
                            .values()
                        ).value

    @deal.safe
    def _chapter_indexer(self) -> Callable[[str], int]:

        current_chapter = 0

        def indexer(paragraph):
            nonlocal current_chapter
            current_chapter += bool(self.chapter.match(paragraph))
            return current_chapter

        return indexer

    @deal.safe
    def _is_valid_span(self) -> Callable[[str], bool]:

        valid = True

        def validator(paragraph):
            nonlocal valid
            bound_marker = self.na_span[1 - valid]
            if bound_marker.match(paragraph):
                valid = not valid
            return valid

        return validator

    @deal.raises(ValueError)
    def _etl_paragraphs(self, doc_path: str) -> Iterator[str]:

        paragraphs = read_paragraphs(Path(doc_path))
        return (IterChain(paragraphs)
                    .thru(ut.strip_(fy.none_fn(*self.slice)))
                    .thru(ut.unique_if_(self.header.match))
                    .filter(self._is_valid_span())
                    .remove(self.references)
                    .remove(self.undesirables)
                    .thru(join_bisections())
               ).value


@deal.has('read')
@deal.raises(AssertionError)
def main() -> None:

    with open('parameters.json', 'r', encoding="utf-8") as json_file:
        params = json.load(json_file)

    book = BookLoader(**params)

    observed_lengths = [len(c) for c in book.chapters]
    expected_lengths = [43, 101, 152, 136, 271, 307, 23]

    assert observed_lengths == expected_lengths

if __name__ == "__main__":
    main()
