"""Article-only HWPX character styles and conservative line-width estimates.

Article roles have explicit fonts and sizes. New styles and missing language
font entries are appended rather than changing shared prices/headings/charts.
Width estimates are advisory: HWP itself remains the pagination authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from .report_brief_style import MAX_ARTICLE_TRACKING, is_domestic_kind, summary_line_limit


_HH = "http://www.hancom.co.kr/hwpml/2011/head"
_HC = "http://www.hancom.co.kr/hwpml/2011/core"
_LANGUAGES = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
_ROLES = {"local": (1300, "휴먼명조", False), "domestic": (1200, "한양중고딕", False), "title": (1200, "한양중고딕", True)}
# A 12pt domestic headline may be tightened further at the user's request.
# This does not relax summary readability or fact/line-limit validation.
MAX_DOMESTIC_TITLE_TRACKING = -30
_BASELINE_HINTS = {"local": "39", "domestic": "30", "title": "51"}
_FONT_FILES = {
    "휴먼명조": Path(r"C:\Program Files (x86)\HNC\Office 2020\HOffice110\Shared\TTF\Hwp\HMKMM.TTF"),
    "굴림": Path(r"C:\Windows\Fonts\gulim.ttc"),
    # The HFT font's TTF counterpart is used only for an advisory estimate.
    "한양중고딕": Path(r"C:\Windows\Fonts\H2GTRM.TTF"),
}
# Intrinsic advances (em) from this report's native HWP PDF Type3 font metrics.
# Apply only to the named HFT faces; unknown characters keep a font fallback.
# In particular HFT spaces are .5em, not the TTF counterpart's .33em. Using the
# actual ASCII widths removes the need for arbitrary line-width safety padding.
_HFT_ASCII = {
    "한양중고딕": {
        " ": .5, "-": .518, ",": .246, ".": .245, "(": .288, ")": .281,
        "%": .867, "/": .263, ":": .247, "$": .529, "*": .369, "<": .583,
        ">": .582, "'": .240, "[": .253, "]": .253,
        "A": .632, "B": .629, "C": .699, "D": .693, "E": .649, "F": .594,
        "G": .751, "H": .689, "I": .246, "J": .470, "L": .539, "M": .803,
        "O": .749, "P": .637, "R": .692, "S": .636, "T": .584, "U": .688,
        "W": .904, "Y": .619, "a": .534, "c": .483, "d": .531, "e": .532,
        "f": .255, "g": .529, "h": .529, "i": .195, "k": .473, "l": .195,
        "m": .809, "n": .529, "o": .539, "p": .535, "r": .310, "s": .480,
        "t": .255, "u": .531, "v": .479, "w": .697, "y": .466,
        "·": .381, "“": .375, "”": .375, "…": 1.0,
        **{digit: .5 for digit in "0123456789"},
    },
    "HCI Poppy": {
        " ": .5, "-": .332, "(": .332, ")": .332, ",": .248, ".": .248,
        ":": .248, "%": .839, "E": .609, "U": .777, "F": .554, "O": .785,
        "B": .609, "~": .605, "M": .945, "k": .554, "g": .554,
        **{digit: .498 for digit in "0123456789"},
    },
    "한양신명조": {"·": .384},
}


class ArticleLayoutError(ValueError):
    """The uploaded style definitions cannot safely be extended."""


@dataclass(frozen=True)
class StyledSegment:
    text: str
    parenthetical: bool
    font_face: str | None = None


def split_parentheticals(text: str) -> tuple[StyledSegment, ...]:
    """Split complete, optionally nested parentheses, retaining every character.

    Unmatched parentheses remain body text. Both ASCII and full-width pairs are
    supported; the delimiters themselves receive the smaller character style.
    """
    pairs = {"(": ")", "（": "）"}
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for index, character in enumerate(text):
        if character in pairs:
            stack.append((character, index))
        elif character in pairs.values():
            if stack and pairs[stack[-1][0]] == character:
                _, start = stack.pop()
                if not stack:
                    spans.append((start, index + 1))
            else:
                stack.clear()
    result: list[StyledSegment] = []
    start = 0
    for left, right in spans:
        if left > start:
            result.append(StyledSegment(text[start:left], False))
        result.append(StyledSegment(text[left:right], True))
        start = right
    if start < len(text):
        result.append(StyledSegment(text[start:], False))
    return tuple(result)


def article_segments(text: str, kind: str) -> tuple[StyledSegment, ...]:
    """Domestic articles are uniformly 12pt, including citation parentheses."""
    if kind in ("domestic", "title"):
        return (StyledSegment(text, False),) if text else ()
    segments = split_parentheticals(text)
    result = []
    previous = ""
    for segment in segments:
        label = (kind == "local" and segment.text == "(현지동향)"
                 and re.fullmatch(r"\s*[-−–]?\s*", previous) is not None)
        # Only the separator needs Gulim's centred dot. Keep the surrounding
        # words, label and factual parentheses in their original role font.
        for part in re.split(r'(·)', segment.text):
            if part:
                result.append(StyledSegment(part, segment.parenthetical and not label,
                                            '굴림' if part == '·' else None))
        previous += segment.text
    return tuple(result)


@lru_cache(maxsize=8)
def _metric_font(face: str):
    path = _FONT_FILES.get(face)
    if path is None or not path.is_file():
        return None
    try:
        from PIL import ImageFont

        return ImageFont.truetype(str(path), 100)
    except (ImportError, OSError, ValueError):
        return None


def _fallback_em(character: str) -> float:
    if unicodedata.combining(character):
        return 0.0
    if character.isspace():
        return 0.32
    if unicodedata.east_asian_width(character) in ("W", "F"):
        return 1.0
    if character in "ilI.,:;'`!|()[]{}":
        return 0.35
    return 0.6


def _tag_attribute(tag: bytes, name: str, value: str) -> bytes:
    expression = rb"(\b" + name.encode("ascii") + rb"\s*=\s*)(['\"])([^'\"]*)\2"
    if not re.search(expression, tag):
        raise ArticleLayoutError("한글파일의 글자 속성을 확인하지 못했습니다.")
    return re.sub(expression, lambda match: match[1] + match[2] + value.encode("ascii") + match[2], tag, count=1)


def _domestic_title_emphasis(raw: bytes) -> bytes:
    """Give article-only headline clones the first page's bold/underline.

    Uploaded reports can point every headline run at an ordinary 12pt body
    style after manual formatting. A matching font and size therefore cannot
    be used as evidence that the headline is already emphasized. Keep the
    original shared definition byte-identical and normalize only its clone.
    """
    opening = re.match(rb"<(?P<prefix>[A-Za-z_][\w.-]*):charPr\b", raw)
    if opening is None:
        raise ArticleLayoutError("국내기사 제목의 강조 서식을 확인하지 못했습니다.")
    prefix = opening['prefix']

    def element(name: bytes) -> bytes:
        tag = re.escape(prefix) + b":" + name
        return rb"<" + tag + rb"\b[^>]*(?:/\s*>|>.*?</" + tag + rb"\s*>)"

    for name in (b'bold', b'underline'):
        expression = element(name)
        if len(re.findall(expression, raw, re.S)) > 1:
            raise ArticleLayoutError("국내기사 제목의 강조 서식이 중복되어 있습니다.")
        raw = re.sub(expression, b'', raw, flags=re.S)
    # CharShapeType orders italic, bold, underline after offset. Choose the
    # last preceding child available in older/minimal uploaded definitions.
    for name in (b'italic', b'offset', b'relSz', b'spacing', b'ratio', b'fontRef'):
        anchor = re.search(element(name), raw, re.S)
        if anchor is not None:
            emphasis = (b'<' + prefix + b':bold/><' + prefix
                        + b':underline type="BOTTOM" shape="SOLID" color="#000000"/>')
            return raw[:anchor.end()] + emphasis + raw[anchor.end():]
    raise ArticleLayoutError("국내기사 제목의 강조 위치를 확인하지 못했습니다.")


def _article_geometry(raw: bytes, source: ET.Element) -> bytes:
    """Force the role's effective size on article-only clones, not shared styles.

    Older/manual uploads may retain relative sizes or width scaling even when
    their nominal height is 1200/1300. Missing properties use standard defaults;
    conditional or duplicate definitions cannot be safely flattened.
    """
    if any(node.tag.rsplit('}', 1)[-1].lower() == 'switch' for node in source.iter()):
        raise ArticleLayoutError("기사의 조건부 글자 서식은 사용할 수 없습니다.")
    prefix = re.match(rb'<([A-Za-z_][\w.-]*):charPr\b', raw)[1]
    for name, value, previous in (('ratio', '100', 'fontRef'),
                                  ('relSz', '100', 'spacing'),
                                  ('offset', '0', 'relSz')):
        nodes = list(source.iter(f'{{{_HH}}}{name}'))
        if (len(nodes) > 1 or nodes != source.findall(f'{{{_HH}}}{name}')
                or (nodes and (len(nodes[0]) or set(nodes[0].attrib) - set(_LANGUAGES)))):
            raise ArticleLayoutError("기사의 글자 크기·장평 서식이 예상 형식과 다릅니다.")
        tag = (b'<' + prefix + b':' + name.encode() + b' '
               + ' '.join(f'{language}="{value}"' for language in _LANGUAGES).encode() + b'/>')
        matches = list(re.finditer(rb'<' + re.escape(prefix) + b':' + name.encode()
                                   + rb'\b[^>]*/\s*>', raw))
        if nodes:
            if len(matches) != 1:
                raise ArticleLayoutError("기사의 글자 크기·장평 태그를 확인하지 못했습니다.")
            match = matches[0]
            raw = raw[:match.start()] + tag + raw[match.end():]
        else:
            anchor = re.search(rb'<' + re.escape(prefix) + b':' + previous.encode()
                               + rb'\b[^>]*/\s*>', raw)
            if anchor is None:
                raise ArticleLayoutError("기사의 글자 크기·장평 위치를 확인하지 못했습니다.")
            raw = raw[:anchor.end()] + tag + raw[anchor.end():]
    return raw


class ArticleLayoutStyles:
    """Append reusable article styles to an otherwise byte-identical header.

    ``available_width`` is expressed in HWPUNIT (100 units = 1 point). The
    returned ``estimatedLines`` is not an actual HWP-rendered line count.
    ``paragraph_prefix`` must be the prefix bound to the paragraph namespace
    in the destination section, normally ``hp``.
    """

    def __init__(
        self,
        header: bytes,
        *,
        local_style_ids: list[str] | tuple[str, ...] | None = None,
        domestic_style_ids: list[str] | tuple[str, ...] | None = None,
        title_style_ids: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", header, re.I):
            raise ArticleLayoutError("외부 엔터티가 포함된 글자 속성은 사용할 수 없습니다.")
        try:
            root = ET.fromstring(header)
        except ET.ParseError as error:
            raise ArticleLayoutError("한글파일의 글자 서식을 읽지 못했습니다.") from error
        if root.tag != f"{{{_HH}}}head":
            raise ArticleLayoutError("한글파일의 머리정보가 올바르지 않습니다.")
        self._header = header
        self._styles = {node.get("id", ""): node for node in root.iter(f"{{{_HH}}}charPr")}
        if not self._styles or any(not key.isdecimal() for key in self._styles):
            raise ArticleLayoutError("한글파일의 글자 속성 번호를 확인하지 못했습니다.")
        self._fonts: dict[str, dict[str, str]] = {}
        self._font_types: dict[str, dict[str, str]] = {}
        for group in root.iter(f"{{{_HH}}}fontface"):
            self._fonts[group.get("lang", "").lower()] = {node.get("id", ""): node.get("face", "") for node in group}
            self._font_types[group.get("lang", "").lower()] = {node.get("id", ""): node.get("type", "").upper() for node in group}
        self._raw_font_groups = {}
        self._raw_fonts = {}
        group_pattern = (rb'<(?P<prefix>[A-Za-z_][\w.-]*):fontface\b[^>]*>'
                         rb'.*?</(?P=prefix):fontface\s*>')
        for group in re.finditer(group_pattern, header, re.S):
            language = re.search(rb'\blang\s*=\s*([\'\"])([A-Za-z]+)\1', group[0])
            if language is None:
                continue
            key = language[2].decode('ascii').lower()
            if key in self._raw_font_groups:
                raise ArticleLayoutError("기사 글꼴의 언어별 정의가 중복되어 있습니다.")
            self._raw_font_groups[key] = group[0]
            font_pattern = (rb'<(?P<prefix>[A-Za-z_][\w.-]*):font\b[^>]*'
                            rb'(?:/\s*>|>.*?</(?P=prefix):font\s*>)')
            self._raw_fonts[key] = {}
            for font in re.finditer(font_pattern, group[0], re.S):
                identity = re.search(rb'\bid\s*=\s*([\'\"])(\d+)\1', font[0])
                if identity is not None:
                    self._raw_fonts[key][identity[2].decode('ascii')] = font[0]
        self._font_additions: dict[str, list[tuple[bytes, set[str]]]] = {}
        self._planned_font_roles: dict[tuple[str, str], set[str]] = {}
        self._used_roles: set[str] = set()
        self._raw_styles: dict[str, bytes] = {}
        pattern = rb"<(?P<prefix>[A-Za-z_][\w.-]*):charPr\b[^>]*(?:/>|>.*?</(?P=prefix):charPr\s*>)"
        for match in re.finditer(pattern, header, re.S):
            identity = re.search(br"\bid\s*=\s*(['\"])(\d+)\1", match[0])
            if identity:
                self._raw_styles[identity[2].decode("ascii")] = match[0]
        if set(self._raw_styles) != set(self._styles):
            raise ArticleLayoutError("한글파일의 글자 속성 구조가 예상 형식과 다릅니다.")
        self._baselines = {
            "local": self._choose_baseline("local", local_style_ids),
            "domestic": self._choose_baseline("domestic", domestic_style_ids),
            "title": self._choose_baseline("title", title_style_ids),
        }
        self._role_references = {}
        for kind, identity in self._baselines.items():
            reference = self._styles[identity].find(f"{{{_HH}}}fontRef")
            selected = dict(reference.attrib) if reference is not None else {}
            # Hangul-only matching is insufficient: the uploaded local style
            # can use Poppy for digits and a different Myeongjo for punctuation.
            # Resolve the requested face in each declared language table. Add
            # an exact copy of its own Hangul font definition when absent;
            # existing definitions and the original shared styles stay intact.
            face = _ROLES[kind][1]
            for language, fonts in self._fonts.items():
                matches = [key for key, name in fonts.items() if name == face]
                if not matches:
                    matches = [self._plan_role_font(language, face, kind)]
                if selected.get(language) not in matches:
                    selected[language] = min(matches, key=lambda key: (not key.isdecimal(), int(key) if key.isdecimal() else key))
                planned = self._planned_font_roles.get((language, selected[language]))
                if planned is not None:
                    planned.add(kind)
            self._role_references[kind] = selected
        self._next_id = max(int(key) for key in self._styles) + 1
        self._added: list[bytes] = []
        self._clones: dict[tuple[str, str, int, int, str | None], str] = {}
        self._paragraphs = {node.get("id", ""): node for node in root.iter(f"{{{_HH}}}paraPr")}
        self._raw_paragraphs = {}
        for match in re.finditer(rb"<(?P<prefix>[A-Za-z_][\w.-]*):paraPr\b[^>]*>.*?</(?P=prefix):paraPr\s*>", header, re.S):
            identity = re.search(br"\bid\s*=\s*(['\"])(\d+)\1", match[0])
            if identity:
                self._raw_paragraphs[identity[2].decode("ascii")] = match[0]
        self._next_paragraph_id = max((int(key) for key in self._paragraphs if key.isdecimal()), default=-1) + 1
        self._added_paragraphs: list[bytes] = []
        self._paragraph_clones: dict[str, str] = {}
        self._hanging_clones: dict[tuple[str, int], str] = {}
        self._word_safe_clones: dict[str, str] = {}
        self._face_references: dict[tuple[str, str], dict[str, str]] = {}

    def _plan_role_font(self, language: str, face: str, kind: str) -> str:
        sources = [identity for identity, name in self._fonts.get('hangul', {}).items() if name == face]
        sources = [identity for identity in sources if identity in self._raw_fonts.get('hangul', {})]
        if language not in self._raw_font_groups or (not sources and face != '굴림'):
            raise ArticleLayoutError(f"기사의 {language} {face} 글꼴을 확인하지 못했습니다.")
        if any(not identity.isdecimal() for identity in self._fonts[language]):
            raise ArticleLayoutError("기사 글꼴의 언어별 번호가 올바르지 않습니다.")
        identity = str(max(map(int, self._fonts[language]), default=-1) + 1)
        if sources:
            source = min(sources, key=int)
            raw = self._raw_fonts['hangul'][source]
            end = raw.index(b'>') + 1
            raw = _tag_attribute(raw[:end], 'id', identity) + raw[end:]
            font_type = self._font_types['hangul'].get(source, '')
        else:
            # Gulim is a standard installed TTF, but older report templates do
            # not declare it. Add a real reference, never rename another face's
            # font metrics/substitution children or alter shared definitions.
            prefix = re.match(rb'<([A-Za-z_][\w.-]*):fontface\b', self._raw_font_groups[language])[1]
            raw = (b'<' + prefix + b':font id="' + identity.encode()
                   + b'" face="' + face.encode('utf-8') + b'" type="TTF" isEmbedded="0"/>')
            font_type = 'TTF'
        roles = {kind}
        self._font_additions.setdefault(language, []).append((raw, roles))
        self._planned_font_roles[(language, identity)] = roles
        self._fonts[language][identity] = face
        self._font_types[language][identity] = font_type
        return identity

    def _references(self, kind: str, face: str | None = None) -> dict[str, str]:
        if face is None:
            return self._role_references[kind]
        key = (kind, face)
        role = f'{kind}:{face}'
        self._used_roles.add(role)
        if key not in self._face_references:
            references = dict(self._role_references[kind])
            for language, fonts in self._fonts.items():
                matches = [identity for identity, name in fonts.items() if name == face]
                identity = min(matches, key=int) if matches else self._plan_role_font(language, face, role)
                references[language] = identity
                planned = self._planned_font_roles.get((language, identity))
                if planned is not None:
                    planned.add(role)
            self._face_references[key] = references
        return self._face_references[key]

    def _face(self, identity: str) -> str:
        reference = self._styles[identity].find(f"{{{_HH}}}fontRef")
        return self._fonts.get("hangul", {}).get(reference.get("hangul", ""), "") if reference is not None else ""

    def _choose_baseline(self, kind: str, candidates: list[str] | tuple[str, ...] | None) -> str:
        height, face, bold = _ROLES[kind]
        available = list(dict.fromkeys(candidates)) if candidates else list(self._styles)
        available = [identity for identity in available if identity in self._styles]
        matching = [identity for identity in available if self._face(identity) == face]
        if not matching:
            matching = [identity for identity in self._styles if self._face(identity) == face]
        if not matching:
            raise ArticleLayoutError(f"기사 본문의 {face} 글꼴 서식을 확인하지 못했습니다.")

        def score(identity: str) -> tuple[int, int, int, int, int]:
            node = self._styles[identity]
            is_bold = node.find(f"{{{_HH}}}bold") is not None
            spacing = node.find(f"{{{_HH}}}spacing")
            normal_spacing = spacing is not None and all(spacing.get(language, "0") == "0" for language in _LANGUAGES)
            return (int(node.get("height", "0") == str(height)), int(is_bold == bold), int(normal_spacing), int(identity == _BASELINE_HINTS[kind]), -int(identity))

        selected = max(matching, key=score)
        if int(self._styles[selected].get("height", "0")) != height:
            # An unrelated price/header style must not become the article body.
            matching = [identity for identity in self._styles if self._face(identity) == face and self._styles[identity].get("height") == str(height)]
            if not matching:
                raise ArticleLayoutError("기사 본문의 기준 글자 크기를 확인하지 못했습니다.")
            selected = max(matching, key=score)
        return selected

    @property
    def baseline_styles(self) -> dict[str, str]:
        return dict(self._baselines)

    def paragraph_style(self, identity: str) -> str:
        """Cap article-only line spacing at 120%, leaving shared styles intact."""
        if identity in self._paragraph_clones:
            return self._paragraph_clones[identity]
        node = self._paragraphs.get(identity)
        raw = self._raw_paragraphs.get(identity)
        spacing = node.find(f"{{{_HH}}}lineSpacing") if node is not None else None
        if raw is None or spacing is None or spacing.get("type") != "PERCENT":
            raise ArticleLayoutError("기사 문단의 줄간격 서식을 확인하지 못했습니다.")
        try:
            previous = int(spacing.get("value", ""))
        except ValueError as error:
            raise ArticleLayoutError("기사 문단의 줄간격 값이 올바르지 않습니다.") from error
        if previous <= 120:
            return identity
        opening_end = raw.index(b">") + 1
        new_id = str(self._next_paragraph_id)
        opening = _tag_attribute(raw[:opening_end], "id", new_id)
        raw = opening + raw[opening_end:]
        pattern = rb"<[A-Za-z_][\w.-]*:lineSpacing\b[^>]*/\s*>"
        match = re.search(pattern, raw)
        if match is None:
            raise ArticleLayoutError("기사 문단의 줄간격 구조가 올바르지 않습니다.")
        raw = raw[:match.start()] + _tag_attribute(match[0], "value", "120") + raw[match.end():]
        self._added_paragraphs.append(raw)
        self._next_paragraph_id += 1
        self._paragraph_clones[identity] = new_id
        return new_id

    def hanging_paragraph_style(self, identity: str, prefix_width_pt: float) -> str:
        """Quick hanging indent at the marker's end, without changing line one.

        Plain Hancom paragraph margin values are doubled URC lengths. Keep the
        low unit bit zero: round a point width to HWPUNIT before doubling it.
        Existing shared styles, alignment and line spacing remain unchanged.
        """
        if not math.isfinite(prefix_width_pt) or prefix_width_pt <= 0:
            raise ArticleLayoutError("기사 줄맞춤 위치가 올바르지 않습니다.")
        prefix_raw = 2 * round(prefix_width_pt * 100)
        if prefix_raw <= 0:
            raise ArticleLayoutError("기사 줄맞춤 위치가 너무 작습니다.")
        specification = (identity, prefix_raw)
        if specification in self._hanging_clones:
            return self._hanging_clones[specification]
        node = self._paragraphs.get(identity)
        raw = self._raw_paragraphs.get(identity)
        margin = node.find(f"{{{_HH}}}margin") if node is not None else None
        if raw is None or margin is None or len(list(node.iter(f"{{{_HH}}}margin"))) != 1:
            raise ArticleLayoutError("기사 문단의 줄맞춤 여백 구조를 확인하지 못했습니다.")
        left = margin.find(f"{{{_HC}}}left")
        indent = margin.find(f"{{{_HC}}}intent")
        if (left is None or indent is None or left.get('unit') != 'HWPUNIT'
                or indent.get('unit') != 'HWPUNIT'):
            raise ArticleLayoutError("기사 문단의 줄맞춤 여백 단위를 확인하지 못했습니다.")
        try:
            old_left, old_indent = int(left.get('value', '')), int(indent.get('value', ''))
        except ValueError as error:
            raise ArticleLayoutError("기사 문단의 줄맞춤 여백 값이 올바르지 않습니다.") from error
        if old_left % 2 or old_indent % 2:
            raise ArticleLayoutError("기사 문단의 줄맞춤 여백 단위 비트가 올바르지 않습니다.")
        new_left = old_left + max(old_indent, 0)
        new_indent = -prefix_raw
        if (old_left, old_indent) == (new_left, new_indent):
            return identity
        new_id = str(self._next_paragraph_id)
        opening_end = raw.index(b'>') + 1
        raw = _tag_attribute(raw[:opening_end], 'id', new_id) + raw[opening_end:]
        for name, value in [('left', new_left), ('intent', new_indent)]:
            expression = rb'<[A-Za-z_][\w.-]*:' + name.encode() + rb'\b[^>]*/\s*>'
            matches = list(re.finditer(expression, raw))
            if len(matches) != 1:
                raise ArticleLayoutError("기사 문단의 줄맞춤 여백 태그가 중복되어 있습니다.")
            match = matches[0]
            raw = raw[:match.start()] + _tag_attribute(match[0], 'value', str(value)) + raw[match.end():]
        self._added_paragraphs.append(raw)
        self._next_paragraph_id += 1
        self._hanging_clones[specification] = new_id
        return new_id

    def word_safe_paragraph_style(self, identity: str) -> str:
        """Keep Korean words whole on an article-only paragraph clone.

        Hancom's enum is counterintuitive: BREAK_WORD keeps Korean words,
        whereas KEEP_WORD permits a break between any two syllables.
        """
        if identity in self._word_safe_clones:
            return self._word_safe_clones[identity]
        raw = self._raw_paragraphs.get(identity)
        if raw is None:
            # Appended fragments carry prefixes declared only by the header.
            raw = next((item for item in self._added_paragraphs
                        if re.search(rb'\bid="' + identity.encode() + rb'"', item.split(b'>', 1)[0])), None)
        if raw is None:
            raise ArticleLayoutError("기사 어절 줄바꿈의 문단 서식을 확인하지 못했습니다.")
        setting = re.search(rb'<[A-Za-z_][\w.-]*:breakSetting\b[^>]*/\s*>', raw)
        if setting is None:
            # Minimal legacy paragraphs lack the optional setting. Leave their
            # defaults intact rather than inventing the remaining attributes.
            return identity
        if re.search(rb'\bbreakNonLatinWord="BREAK_WORD"', setting[0]):
            return identity
        changed = _tag_attribute(setting[0], 'breakNonLatinWord', 'BREAK_WORD')
        new_id = str(self._next_paragraph_id)
        raw = raw[:setting.start()] + changed + raw[setting.end():]
        end = raw.index(b'>') + 1
        raw = _tag_attribute(raw[:end], 'id', new_id) + raw[end:]
        self._added_paragraphs.append(raw)
        self._next_paragraph_id += 1
        self._word_safe_clones[identity] = new_id
        return new_id

    def _style(self, kind: str, parenthetical: bool, tracking: int, face: str | None = None) -> str:
        self._used_roles.add(kind)
        base = self._baselines[kind]
        height = _ROLES[kind][0] - (200 if parenthetical and kind == "local" else 0)
        # A manually flattened upload can use one baseline for both body and
        # headline. They must not reuse a clone with different emphasis.
        specification = (kind, base, height, tracking, face)
        if specification in self._clones:
            return self._clones[specification]
        raw = self._raw_styles[base]
        start_end = raw.index(b">") + 1
        opening = _tag_attribute(raw[:start_end], "id", str(self._next_id))
        opening = _tag_attribute(opening, "height", str(height))
        opening = _tag_attribute(opening, "textColor", "#000000")
        raw = opening + raw[start_end:]
        raw = _article_geometry(raw, self._styles[base])
        if kind == 'title':
            raw = _domestic_title_emphasis(raw)
        else:
            # A manually flattened upload can supply only an emphasized
            # matching-font baseline. Emphasis belongs to headlines, not to
            # local or domestic summary bodies.
            for name in (b'bold', b'underline'):
                expression = (rb'<(?P<prefix>[A-Za-z_][\w.-]*):' + name
                              + rb'\b[^>]*(?:/\s*>|>.*?</(?P=prefix):' + name + rb'\s*>)')
                raw = re.sub(expression, b'', raw, flags=re.S)
        reference = re.search(rb"<[A-Za-z_][\w.-]*:fontRef\b[^>]*/\s*>", raw)
        if reference is None:
            raise ArticleLayoutError("기사의 글꼴 참조 구조를 확인하지 못했습니다.")
        tag = reference[0]
        for language, identity in self._references(kind, face).items():
            tag = _tag_attribute(tag, language, identity)
        raw = raw[:reference.start()] + tag + raw[reference.end():]
        spacing_pattern = rb"<(?P<prefix>[A-Za-z_][\w.-]*):spacing\b[^>]*\/\s*>"
        spacing = re.search(spacing_pattern, raw)
        if spacing is None:
            raise ArticleLayoutError("기사 글자의 자간 속성을 확인하지 못했습니다.")
        tag = spacing[0]
        for language in _LANGUAGES:
            tag = _tag_attribute(tag, language, str(tracking))
        raw = raw[:spacing.start()] + tag + raw[spacing.end():]
        identity = str(self._next_id)
        self._next_id += 1
        self._added.append(raw)
        self._clones[specification] = identity
        return identity

    def estimate_width(self, text: str, *, kind: str = "local", tracking: int = 0) -> float:
        """Advisory width in points, accounting for smaller parentheses."""
        if kind not in _ROLES:
            raise ArticleLayoutError("지원하지 않는 기사 글자 역할입니다.")
        references = self._role_references[kind]
        widths = []
        for segment in article_segments(text, kind):
            font = _metric_font(segment.font_face or self._face(self._baselines[kind]))
            size = (_ROLES[kind][0] - (200 if segment.parenthetical else 0)) / 100
            for character in segment.text:
                language = ("symbol" if ord(character) > 127 and unicodedata.category(character)[0] in ("P", "S")
                            else "hangul" if unicodedata.east_asian_width(character) in ("W", "F") else "latin")
                advance = float(font.getlength(character)) / 100 if font is not None else _fallback_em(character)
                reference = references.get(language, "")
                face = segment.font_face or self._fonts.get(language, {}).get(reference, "")
                if not segment.font_face and self._font_types.get(language, {}).get(reference) == "HFT":
                    advance = _HFT_ASCII.get(face, {}).get(character, advance)
                    # Native HWP's synthetic HFT bold adds .05em per glyph,
                    # including Latin/digits in the smaller citation. PDF font
                    # intrinsic Widths do not include that advance adjustment.
                    # Guard by the actual face/type/style, not by headline role.
                    if (face == "한양중고딕" and kind == 'title'
                            and not unicodedata.combining(character)):
                        advance += .05
                glyph_width = advance * size
                widths.append(glyph_width)
        # Tracking follows a glyph; the LAST glyph has no following spacing.
        # Omitting it from the first instead can undercount a terminal Korean
        # syllable by >1pt and wrongly approve one-character overflows.
        return max(0.0, sum(widths) + sum(widths[:-1]) * tracking / 100)

    def _rounded_advances(self, text: str, kind: str, tracking: int = 0) -> tuple[list[int], list[int]]:
        """Hancom's 4-HWPUNIT glyph rounding for advisory line boundaries."""
        base = self._styles[self._baselines[kind]]
        font_space = base.get('useFontSpace', '0') in ('1', 'true')
        unspaced, spaced = [], []
        for segment in article_segments(text, kind):
            height = _ROLES[kind][0] - (200 if segment.parenthetical else 0)
            for character in segment.text:
                if character in (' ', '\u00a0') and not font_space:
                    units = height // 4 // 2
                else:
                    # Use the complete segment to retain smaller-parenthesis
                    # and dot font semantics when measuring single glyphs.
                    face = segment.font_face or self._face(self._baselines[kind])
                    font = _metric_font(face)
                    width = float(font.getlength(character)) / 100 if font else _fallback_em(character)
                    language = ('symbol' if ord(character) > 127 and unicodedata.category(character)[0] in ('P', 'S')
                                else 'hangul' if unicodedata.east_asian_width(character) in ('W', 'F') else 'latin')
                    reference = self._role_references[kind].get(language, '')
                    if not segment.font_face and self._font_types.get(language, {}).get(reference) == 'HFT':
                        width = _HFT_ASCII.get(face, {}).get(character, width)
                        if face == '한양중고딕' and kind == 'title' and not unicodedata.combining(character):
                            width += .05
                    units = math.floor(width * height / 4 + .5)
                delta = math.floor(abs(units * tracking / 100) + .5)
                unspaced.append(units * 4)
                spaced.append(max(0, units + (delta if tracking > 0 else -delta)) * 4)
        return unspaced, spaced

    @staticmethod
    def _terminal_width(unspaced: list[int], spaced: list[int], end: int | None = None) -> int:
        end = len(spaced) if end is None else end
        return sum(spaced[:end - 1]) + unspaced[end - 1] if end else 0

    def _word_line_layout(self, text: str, kind: str, tracking: int, width: int) -> tuple[list[str], int | None]:
        """Whole-word line previews, and a split word to finish on line one."""
        from hwpx.form_fit.measure import TextStyle, hancom_line_starts
        unspaced, advances = self._rounded_advances(text, kind, tracking)
        first_end = 0
        while first_end < len(text) and self._terminal_width(unspaced, advances, first_end + 1) <= width:
            first_end += 1
        target = None
        if 0 < first_end < len(text) and all(unicodedata.category(ch)[0] in 'LMN' for ch in text[first_end - 1:first_end + 1]):
            match = re.match(r'\S+', text[first_end:])
            if match:
                target = first_end + match.end()
        marker = re.match(r'^\s*[-−–]\s*', text)
        hanging = round(self.estimate_width(marker[0], kind=kind, tracking=tracking) * 100) if marker else 0
        # A conservative boundary budget restores the terminal advance; the
        # last glyph has no negative tracking. This is not arbitrary padding.
        terminal = max((a - b for a, b in zip(unspaced, advances)), default=0)
        starts = hancom_line_starts(text, [width - terminal, width - hanging - terminal],
                                   _ROLES[kind][0] / 100, TextStyle(break_non_latin_word='BREAK_WORD'),
                                   advances=dict(enumerate(advances)))
        lines = [text[start:end].strip() for start, end in zip(starts, starts[1:] + [len(text)])]
        return lines, target

    def marker_prefix_width(
        self,
        text: str,
        *,
        kind: str,
        marker_length: int,
        available_width: int,
        paragraph_style_id: str,
        tracking: int = 0,
    ) -> float:
        """Measure the caret anchor, including a wrapped JUSTIFY line's spaces.

        Hancom rounds glyph advances to 1/1800 inch (four HWPUNIT), then
        distributes the first line's remaining room over its internal spaces.
        Its quick-indent action uses that displayed caret, not the nominal
        marker width. Only line-break calculation uses python-hwpx; the
        document remains a byte-preserving ZIP-level edit. Older deployments
        without that optional measurement engine retain the nominal estimate.
        """
        if (kind not in _ROLES or not isinstance(marker_length, int)
                or not 0 < marker_length <= len(text) or available_width <= 0):
            raise ArticleLayoutError("기사 줄맞춤의 문구 또는 사용 너비가 올바르지 않습니다.")
        paragraph = self._paragraphs.get(paragraph_style_id)
        if paragraph is None:
            raise ArticleLayoutError("기사 줄맞춤의 문단 서식을 확인하지 못했습니다.")
        alignment = paragraph.find(f"{{{_HH}}}align")
        horizontal = alignment.get('horizontal', '') if alignment is not None else ''
        if horizontal not in ('JUSTIFY', 'LEFT', 'CENTER', 'RIGHT', 'DISTRIBUTE', 'DISTRIBUTE_SPACE'):
            raise ArticleLayoutError("기사 줄맞춤의 문단 정렬을 확인하지 못했습니다.")
        nominal = self.estimate_width(text[:marker_length], kind=kind, tracking=tracking)
        if horizontal != 'JUSTIFY':
            return nominal

        margins = list(paragraph.iter(f"{{{_HH}}}margin"))
        margin = paragraph.find(f"{{{_HH}}}margin")
        if margin is None or len(margins) != 1:
            raise ArticleLayoutError("기사 줄맞춤의 문단 여백 구조를 확인하지 못했습니다.")
        lengths = {}
        for name in ('left', 'right', 'intent'):
            elements = margin.findall(f"{{{_HC}}}{name}")
            if len(elements) != 1 or elements[0].get('unit') != 'HWPUNIT':
                raise ArticleLayoutError("기사 줄맞춤의 문단 여백 단위를 확인하지 못했습니다.")
            try:
                raw = int(elements[0].get('value', ''))
            except ValueError as error:
                raise ArticleLayoutError("기사 줄맞춤의 문단 여백 값이 올바르지 않습니다.") from error
            if raw % 2:
                raise ArticleLayoutError("기사 줄맞춤의 문단 여백 단위 비트가 올바르지 않습니다.")
            lengths[name] = raw // 2
        first_width = available_width - lengths['left'] - lengths['right'] - max(lengths['intent'], 0)
        first_width = math.floor(first_width / 4) * 4
        if first_width <= 0:
            raise ArticleLayoutError("기사 줄맞춤의 첫 줄 사용 너비가 올바르지 않습니다.")
        try:
            condense = int(paragraph.get('condense', '0'))
        except ValueError as error:
            raise ArticleLayoutError("기사 줄맞춤의 최소 공백 값이 올바르지 않습니다.") from error
        if not 0 <= condense <= 75:
            raise ArticleLayoutError("기사 줄맞춤의 최소 공백 값이 올바르지 않습니다.")
        # Compressed-space paragraphs need the renderer's actual per-space
        # compression. Retain a safe nominal anchor rather than invent it.
        if condense:
            return nominal
        try:
            from hwpx.form_fit.measure import TextStyle, hancom_line_starts
        except ImportError:
            return nominal

        base = self._styles[self._baselines[kind]]
        use_font_space = base.get('useFontSpace', '0') in ('1', 'true')
        advances = []
        for segment in article_segments(text, kind):
            height = _ROLES[kind][0] - (200 if segment.parenthetical else 0)
            size_scale = height / _ROLES[kind][0]
            for character in segment.text:
                language = ("symbol" if ord(character) > 127 and unicodedata.category(character)[0] in ("P", "S")
                            else "hangul" if unicodedata.east_asian_width(character) in ("W", "F") else "latin")
                if character in (' ', '\u00a0') and not use_font_space:
                    units = height // 4 // 2
                else:
                    glyph_pt = self.estimate_width(character, kind=kind) * size_scale
                    units = math.floor(glyph_pt * 25 + .5)
                if tracking:
                    extra = math.floor(abs(units * tracking / 100) + .5)
                    units += extra if tracking > 0 else -extra
                advances.append(max(0, units) * 4)

        breaks = paragraph.find(f"{{{_HH}}}breakSetting")
        shape = TextStyle(
            break_latin_word=breaks.get('breakLatinWord', 'KEEP_WORD') if breaks is not None else 'KEEP_WORD',
            break_non_latin_word=breaks.get('breakNonLatinWord', 'BREAK_WORD') if breaks is not None else 'BREAK_WORD',
            condense=condense,
        )
        starts = hancom_line_starts(text, [first_width], _ROLES[kind][0] / 100, shape,
                                   advances=dict(enumerate(advances)))
        if len(starts) < 2:
            return nominal
        first_end = starts[1]
        # The first trailing blank hangs past the right edge; it is not part
        # of the room distributed between words. Leading blanks remain in
        # the intrinsic width but do not participate in justification.
        while first_end > 0 and text[first_end - 1] == ' ':
            first_end -= 1
        first_line = text[:first_end]
        inner_spaces = first_line.lstrip(' ').count(' ')
        prefix_spaces = text[:marker_length].lstrip(' ').count(' ')
        if not inner_spaces or marker_length > first_end:
            return nominal
        slack = max(0, first_width - sum(advances[:first_end]))
        space_extra = math.floor(slack / inner_spaces)
        return (sum(advances[:marker_length]) + prefix_spaces * space_extra) / 100

    def measure_layout(
        self,
        text: str,
        *,
        kind: str = "local",
        available_width: int = 46320,
        max_tracking: int | None = None,
        max_lines: int | None = None,
    ) -> dict[str, int | float | str | bool | list[str]]:
        """Read-only fit decision; no shared or appended styles are changed."""
        if kind not in _ROLES or (max_lines is not None and max_lines not in (1, 2)):
            raise ArticleLayoutError("기사 글자 서식 역할 또는 최대 줄 수가 올바르지 않습니다.")
        if available_width <= 0:
            raise ArticleLayoutError("기사 문단의 사용 너비를 확인하지 못했습니다.")
        role_bound = MAX_DOMESTIC_TITLE_TRACKING if kind == 'title' else MAX_ARTICLE_TRACKING
        bound = role_bound if max_tracking is None else max(role_bound, min(0, int(max_tracking)))
        # Use the entire available line, without arbitrary safety padding. The
        # estimate is advisory; final rendering still depends on HWP's fonts.
        usable = available_width / 100
        tracking = 0
        natural_width = measured = self.estimate_width(text, kind=kind)
        decision = "natural-one-line"
        if measured > usable:
            # A long sentence should read as two natural lines, not two cramped
            # lines. Only slightly overflowing text is eligible for tightening.
            if (max_lines == 1 or natural_width < usable * 1.5) and self.estimate_width(text, kind=kind, tracking=bound) <= usable:
                while measured > usable and tracking > bound:
                    tracking -= 1
                    measured = self.estimate_width(text, kind=kind, tracking=tracking)
                decision = "minimum-tracking-one-line"
            else:
                decision = "natural-wrap"
        marker = re.match(r"^\s*[-−–]\s*", text)
        continuation_margin = self.estimate_width(marker[0], kind=kind) if marker else 0
        capacity = (usable * max_lines - continuation_margin * (max_lines - 1)) if max_lines else float('inf')
        if max_lines == 2 and measured > capacity:
            while measured > capacity and tracking > bound:
                tracking -= 1
                measured = self.estimate_width(text, kind=kind, tracking=tracking)
            decision = "minimum-tracking-two-lines" if measured <= capacity else "line-limit-exceeded"
        line_texts = []
        if max_lines == 2 and measured > usable and _metric_font(self._face(self._baselines[kind])) is not None:
            try:
                line_texts, crossing_end = self._word_line_layout(text, kind, tracking, available_width)
                if crossing_end is not None:
                    # Complete the word that would otherwise lose its final
                    # syllable. Pick the first (least negative) usable step;
                    # never tighten merely to fill arbitrary whitespace.
                    for candidate in range(tracking - 1, bound - 1, -1):
                        unspaced, spaced = self._rounded_advances(text, kind, candidate)
                        if self._terminal_width(unspaced, spaced, crossing_end) <= available_width:
                            candidate_lines, _ = self._word_line_layout(text, kind, candidate, available_width)
                            if len(candidate_lines) <= max_lines:
                                tracking = candidate
                                measured = self.estimate_width(text, kind=kind, tracking=tracking)
                                line_texts = candidate_lines
                                decision = 'minimum-tracking-whole-word'
                            break
            except ImportError:
                # Optional advisory engine absent: preserve content and the
                # article paragraph's whole-word setting, not manual breaks.
                pass
        within_limit = measured <= capacity and (not line_texts or len(line_texts) <= (max_lines or len(line_texts)))
        if max_lines == 1 and not within_limit:
            decision = "line-limit-exceeded"
        return {
            "tracking": tracking,
            "minimumTracking": bound,
            "bodySizePt": _ROLES[kind][0] // 100,
            "parentheticalSizePt": (_ROLES[kind][0] - (200 if kind == "local" else 0)) // 100,
            "localLabelSizePt": 13 if kind == "local" else 0,
            "naturalWidthPt": round(natural_width, 2),
            "naturalLineRatio": round(natural_width / usable, 3),
            "fitDecision": decision,
            "estimatedWidthPt": round(measured, 2),
            "availableWidthPt": round(usable, 2),
            "estimatedLines": len(line_texts) if line_texts else max(1, math.ceil(measured / usable)),
            "oneLine": measured <= usable,
            "allowedLines": max_lines or 0,
            "withinLineLimit": within_limit,
            "estimatedLineTexts": line_texts,
            "measurement": "font-metric-estimate" if _metric_font(self._face(self._baselines[kind])) is not None else "em-estimate",
        }

    def build_runs(
        self,
        text: str,
        *,
        kind: str = "local",
        available_width: int = 46320,
        max_tracking: int | None = None,
        paragraph_prefix: str = "hp",
        max_lines: int | None = None,
    ) -> tuple[bytes, dict[str, int | float | str | bool | list[str]]]:
        if not re.fullmatch(r"[A-Za-z_][\w.-]*", paragraph_prefix):
            raise ArticleLayoutError("기사 글자 서식의 네임스페이스가 올바르지 않습니다.")
        layout = self.measure_layout(text, kind=kind, available_width=available_width,
                                     max_tracking=max_tracking, max_lines=max_lines)
        chunks: list[bytes] = []
        for segment in article_segments(text, kind):
            identity = self._style(kind, segment.parenthetical, int(layout['tracking']), segment.font_face)
            chunks.append((f'<{paragraph_prefix}:run charPrIDRef="{identity}"><{paragraph_prefix}:t>'
                           + escape(segment.text) + f'</{paragraph_prefix}:t></{paragraph_prefix}:run>').encode("utf-8"))
        return b"".join(chunks), layout

    @staticmethod
    def _append_styles(header: bytes, container: str, count_before: int, additions: list[bytes]) -> bytes:
        if not additions:
            return header
        expression = rb"<(?P<prefix>[A-Za-z_][\w.-]*):" + container.encode("ascii") + rb"\b(?P<attrs>[^>]*)>"
        opening = re.search(expression, header)
        if opening is None:
            raise ArticleLayoutError("한글파일의 서식 속성 목록을 확인하지 못했습니다.")
        closing = re.search(rb"</" + re.escape(opening["prefix"]) + b":" + container.encode("ascii") + rb"\s*>", header[opening.end():])
        if closing is None:
            raise ArticleLayoutError("한글파일의 서식 속성 목록이 닫혀 있지 않습니다.")
        count = re.search(br"\bitemCnt\s*=\s*(['\"])(\d+)\1", opening[0])
        if count is None or int(count[2]) != count_before:
            raise ArticleLayoutError("한글파일의 서식 속성 개수가 올바르지 않습니다.")
        changed_opening = _tag_attribute(opening[0], "itemCnt", str(count_before + len(additions)))
        insertion = opening.end() + closing.start()
        return header[:opening.start()] + changed_opening + header[opening.end():insertion] + b"".join(additions) + header[insertion:]

    def patched_header(self) -> bytes:
        result = self._append_styles(self._header, "charProperties", len(self._styles), self._added)
        result = self._append_styles(result, "paraProperties", len(self._paragraphs), self._added_paragraphs)
        for language, planned in self._font_additions.items():
            last_used = max((index for index, (_, roles) in enumerate(planned)
                             if roles & self._used_roles), default=-1)
            # Keep appended IDs contiguous even when a later role is the only
            # one used (e.g. both local and domestic faces were missing).
            additions = [raw for raw, _ in planned[:last_used + 1]]
            if not additions:
                continue
            original = self._raw_font_groups[language]
            closing = re.search(rb'</[A-Za-z_][\w.-]*:fontface\s*>$', original)
            end = original.index(b'>') + 1
            count = re.search(rb'\bfontCnt\s*=\s*([\'\"])(\d+)\1', original[:end])
            if (closing is None or count is None
                    or int(count[2]) != len(self._raw_fonts.get(language, {}))):
                raise ArticleLayoutError("기사 글꼴의 언어별 개수가 올바르지 않습니다.")
            opening = _tag_attribute(original[:end], 'fontCnt', str(int(count[2]) + len(additions)))
            updated = opening + original[end:closing.start()] + b''.join(additions) + original[closing.start():]
            if result.count(original) != 1:
                raise ArticleLayoutError("기사 글꼴의 언어별 목록을 확인하지 못했습니다.")
            result = result.replace(original, updated, 1)
        try:
            ET.fromstring(result)
        except ET.ParseError as error:
            raise ArticleLayoutError("기사 글자 서식 저장 검증에 실패했습니다.") from error
        return result


@lru_cache(maxsize=1)
def _reference_styles() -> ArticleLayoutStyles:
    template = Path(__file__).resolve().parents[1] / 'report_template/weekly_overseas_market_report_table_template.hwpx'
    with zipfile.ZipFile(template) as package:
        return ArticleLayoutStyles(package.read('Contents/header.xml'))


def summary_reference_layout(summary: str, key: str) -> dict[str, int | float | str | bool | list[str]]:
    """Draft guard for our report template; the uploaded file is checked again.

    Character count alone cannot enforce a line: Korean glyphs, numbers and
    smaller factual parentheses all have different advances. This cached
    reference measurement is read-only, local and never calls an AI model.
    """
    domestic = is_domestic_kind(key)
    return _reference_styles().measure_layout(
        (' - ' if domestic else ' - (현지동향) ') + summary,
        kind='domestic' if domestic else 'local',
        available_width=46604 if domestic else 46320,
        max_lines=summary_line_limit(key),
    )
