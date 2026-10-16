"""Insert the twelve reviewed article briefs into an uploaded HWPX report.

This is deliberately a ZIP/byte-span editor, not an XML serializer. Only the
article paragraphs and their cached line positions change. Article-only
character styles are appended; prices, pictures, existing styles and table
geometry remain untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any
from xml.parsers import expat
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

from src.report_brief_style import MAX_ARTICLE_TRACKING, SECTION_AUDIENCES, SUMMARY_LIMITS, SUMMARY_MIN_LENGTH, summary_line_limit
from src.article_hwpx_layout import ArticleLayoutError, ArticleLayoutStyles
from src.article_titles import clean_article_title, format_domestic_article_title, normalize_article_publisher


class ArticleHwpxError(ValueError):
    """A safe, user-facing error; no partly edited report is returned."""


_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph}"
_HS = "http://www.hancom.co.kr/hwpml/2011/section}"
_SECTION_NAME = re.compile(r"Contents/section\d+\.xml\Z")
_MAX_ARCHIVE = 40 * 1024 * 1024
_MAX_MEMBER = 24 * 1024 * 1024
_MAX_EXPANDED = 100 * 1024 * 1024
_MAX_ENTRIES = 2048
_GROUPS = (
    ("beef", ("쇠고기", "소고기"), (("us", "미국"), ("australia", "호주")), "domestic"),
    ("pork", ("돼지고기",), (("us_pork", "미국"), ("eu_pork", "EU(독일)")), "domestic_pork"),
    ("chicken", ("육계", "닭고기"), (("us_chicken", "미국"), ("brazil_chicken", "브라질")), "domestic_chicken"),
    ("egg", ("계란", "달걀"), (("us_egg", "미국"), ("japan_egg", "일본")), "domestic_egg"),
)
ARTICLE_SLOT_KEYS = tuple(key for _, _, local, domestic in _GROUPS for key in (*[item[0] for item in local], domestic))
_LOCAL_PREFIX = re.compile(r"^(\s*[-−–]\s*\(현지동향\)\s*)(.*)\Z", re.S)
_SUMMARY_PREFIX = re.compile(r"^(\s*[-−–]\s*)(.*)\Z", re.S)
# A bullet-only title is a deliberately blank article slot, not stale content.
# Retaining the template's structural markers makes partially filled reports
# safely discoverable when the user later reapplies a finished draft.
_TITLE = re.compile(r"^(\s*[∙·•]\s*)(?:([“\"].*[”\"])(\s*\([^\n]+\)\s*))?\Z", re.S)
_BLANK_STATUSES = frozenset(("missing", "no_article", "source_error", "summary_error", "model_unavailable"))
_NAMESPACES = {
    "http://www.hancom.co.kr/hwpml/2011/head": "hh",
    "http://www.hancom.co.kr/hwpml/2011/core": "hc",
    "http://www.hancom.co.kr/hwpml/2011/paragraph": "hp",
    "http://www.hancom.co.kr/hwpml/2011/section": "hs",
}


@dataclass(eq=False)
class _Node:
    name: str
    attributes: dict[str, str]
    start: int
    open_end: int
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    pieces: list[str | _Node] = field(default_factory=list)
    close_start: int = 0
    end: int = 0
    empty: bool = False

    @property
    def text(self) -> str:
        if self.name in (_HP + "fwSpace", _HP + "tab"):
            return " "
        if self.name == _HP + "lineBreak":
            return "\n"
        return "".join(piece if isinstance(piece, str) else piece.text for piece in self.pieces)

    @property
    def texts(self) -> list[_Node]:
        return [text for run in self.children if run.name == _HP + "run"
                for text in run.children if text.name == _HP + "t"]

    @property
    def own_text(self) -> str:
        return "".join(node.text for node in self.texts)

    def ancestor(self, name: str) -> _Node | None:
        node = self.parent
        while node is not None:
            if node.name == name:
                return node
            node = node.parent
        return None


@dataclass
class _Slot:
    key: str
    section: str
    paragraph: _Node
    title: _Node | None = None
    continuations: tuple[_Node, ...] = ()


def _tag_end(data: bytes, start: int) -> int:
    quote = None
    for position in range(start, len(data)):
        value = data[position]
        if quote is not None:
            if value == quote:
                quote = None
        elif value in (34, 39):
            quote = value
        elif value == 62:
            return position + 1
    raise ArticleHwpxError("한글파일의 본문 XML이 올바르지 않습니다.")


def _parse_section(data: bytes) -> tuple[_Node, list[_Node]]:
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.I):
        raise ArticleHwpxError("외부 엔터티가 포함된 한글파일은 사용할 수 없습니다.")
    encoding = re.search(br"<\?xml\b[^>]*\bencoding\s*=\s*['\"]([^'\"]+)", data[:300], re.I)
    if encoding and encoding[1].lower() not in (b"utf-8", b"utf8"):
        raise ArticleHwpxError("UTF-8 형식의 HWPX 한글파일을 넣어 주세요.")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ArticleHwpxError("한글파일의 본문 인코딩을 읽지 못했습니다.") from error
    parser = expat.ParserCreate(namespace_separator="}")
    stack: list[_Node] = []
    nodes: list[_Node] = []

    def start(name: str, attributes: dict[str, str]) -> None:
        if len(nodes) >= 200000 or len(stack) >= 128:
            raise ArticleHwpxError("한글파일의 본문 구조가 너무 크거나 깊습니다.")
        position = parser.CurrentByteIndex
        ending = _tag_end(data, position)
        parent = stack[-1] if stack else None
        node = _Node(name, attributes, position, ending, parent,
                     empty=data[position:ending].rstrip().endswith(b"/>"))
        if parent is not None:
            parent.children.append(node)
            parent.pieces.append(node)
        nodes.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        node = stack.pop()
        node.close_start = node.open_end if node.empty else parser.CurrentByteIndex
        node.end = node.open_end if node.empty else _tag_end(data, node.close_start)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = lambda value: stack[-1].pieces.append(value) if stack else None
    parser.ExternalEntityRefHandler = lambda *_args: 0
    try:
        parser.Parse(data, True)
    except (expat.ExpatError, IndexError) as error:
        raise ArticleHwpxError("한글파일의 본문 XML을 읽지 못했습니다.") from error
    if not nodes or nodes[0].name != _HS + "sec":
        raise ArticleHwpxError("HWPX 한글파일의 본문 영역을 확인하지 못했습니다.")
    if len(nodes) > 200000:
        raise ArticleHwpxError("한글파일의 본문 구조가 너무 큽니다.")
    return nodes[0], [node for node in nodes if node.name == _HP + "p"]


def _canonical_namespaces(data: bytes) -> bytes:
    """Required namespace post-processing, without reserializing the section."""
    declarations = re.findall(br"xmlns:([A-Za-z_][\w.-]*)\s*=\s*(['\"])([^'\"]+)\2", data)
    bindings = {alias.decode(): uri.decode() for alias, _, uri in declarations}
    for alias, _, uri in declarations:
        old = alias.decode()
        new = _NAMESPACES.get(uri.decode())
        if not re.fullmatch(r"ns\d+", old) or not new:
            continue
        if new in bindings and bindings[new] != uri.decode():
            raise ArticleHwpxError("한글파일의 XML 네임스페이스가 충돌합니다.")
        declaration = rb"\s+xmlns:" + re.escape(alias) + rb"\s*=\s*(['\"])[^'\"]+\1"
        if new in bindings:
            data = re.sub(declaration, b"", data)
        else:
            data = re.sub(rb"\bxmlns:" + re.escape(alias) + rb"(?=\s*=)", b"xmlns:" + new.encode(), data)
            bindings[new] = uri.decode()
        data = re.sub(rb"(<\/?|\s)" + re.escape(alias) + rb":(?=[A-Za-z_])",
                      lambda match: match[1] + new.encode() + b":", data)
    _parse_section(data)
    return data


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _discover_slots(parts: dict[str, bytes]) -> dict[str, _Slot]:
    paragraphs: list[tuple[str, _Node]] = []
    for name in sorted(parts, key=lambda item: int(re.search(r"\d+", item)[0])):
        _, nodes = _parse_section(parts[name])
        paragraphs.extend((name, node) for node in nodes)
    headings: dict[str, int] = {}
    for index, (_, paragraph) in enumerate(paragraphs):
        text = _normalized(paragraph.own_text)
        if paragraph.ancestor(_HP + "tc") is not None or "수급및가격동향" not in text:
            continue
        for species, names, _, _ in _GROUPS:
            if any(text == "□" + name + "수급및가격동향" for name in names):
                if species in headings:
                    raise ArticleHwpxError("축종별 기사 위치가 중복되어 적용할 수 없습니다.")
                headings[species] = index
    if set(headings) != {group[0] for group in _GROUPS}:
        raise ArticleHwpxError("소·돼지·육계·계란의 수급 및 가격 동향 양식을 확인해 주세요.")
    bounds = sorted(headings.values()) + [len(paragraphs)]
    slots: dict[str, _Slot] = {}
    for species, _, local, domestic in _GROUPS:
        beginning = headings[species]
        ending = bounds[bounds.index(beginning) + 1]
        group = paragraphs[beginning + 1:ending]
        country_nodes = [(index, name, node) for index, (name, node) in enumerate(group)
                         if node.own_text.strip().startswith("○")]
        if len(country_nodes) != 2:
            raise ArticleHwpxError("축종별 두 국가의 기사 위치를 확인하지 못했습니다.")
        for position, (key, country) in enumerate(local):
            index, name, heading = country_nodes[position]
            if _normalized(heading.own_text) != "○" + country:
                raise ArticleHwpxError("한글파일의 국가 순서가 예상 양식과 다릅니다.")
            stop = country_nodes[position + 1][0] if position + 1 < len(country_nodes) else len(group)
            candidates = [(section, node) for section, node in group[index + 1:stop]
                          if _LOCAL_PREFIX.fullmatch(node.own_text)]
            if len(candidates) != 1 or candidates[0][1].ancestor(_HP + "tc") is not heading.ancestor(_HP + "tc"):
                raise ArticleHwpxError(f"{country}의 (현지동향) 기사 위치를 확인하지 못했습니다.")
            section, paragraph = candidates[0]
            slots[key] = _Slot(key, section, paragraph)
        titles = [(name, node) for name, node in group if _TITLE.fullmatch(node.own_text)]
        if len(titles) != 1:
            raise ArticleHwpxError("국내기사 네모칸의 제목 위치가 없거나 중복되어 있습니다.")
        name, title = titles[0]
        cell = title.ancestor(_HP + "tc")
        if cell is None or title.parent is None or title.parent.name != _HP + "subList":
            raise ArticleHwpxError("국내기사 네모칸의 본문 구조를 확인하지 못했습니다.")
        siblings = [node for node in title.parent.children if node.name == _HP + "p" and node.own_text.strip()]
        after = siblings[siblings.index(title) + 1:]
        if (not after or len(after) > 3 or not _SUMMARY_PREFIX.fullmatch(after[0].own_text)
                or any(node.own_text.lstrip().startswith(("∙", "•", "○", "□", "※", "-")) for node in after[1:])):
            raise ArticleHwpxError("국내기사 네모칸의 요약 위치를 확인하지 못했습니다.")
        slots[domestic] = _Slot(domestic, name, after[0], title, tuple(after[1:]))
    if set(slots) != set(ARTICLE_SLOT_KEYS):
        raise ArticleHwpxError("12개 기사 적용 위치를 모두 확인하지 못했습니다.")
    return slots


def _clean(value: Any, *, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArticleHwpxError(f"{label}이 비어 있습니다. 기사 초안을 먼저 완성해 주세요.")
    if (any(ord(char) < 32 and char not in "\t\n\r" for char in value)
            or any(0xD800 <= ord(char) <= 0xDFFF or ord(char) in (0xFFFE, 0xFFFF) for char in value)):
        raise ArticleHwpxError(f"{label}에 사용할 수 없는 문자가 있습니다.")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise ArticleHwpxError(f"{label}이 너무 깁니다. 보고서용 초안을 사용해 주세요.")
    return cleaned


def _draft_values(draft: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    from src.overseas_article_digest import normalize_report_spacing
    from src.livestock_article_draft import _same_domestic_article

    sections = draft.get("sections") if isinstance(draft, dict) else None
    if not isinstance(sections, dict):
        raise ArticleHwpxError("기사 초안 정보가 없습니다. 기사 초안을 먼저 작성해 주세요.")
    if set(sections) - set(ARTICLE_SLOT_KEYS):
        raise ArticleHwpxError("알 수 없는 기사 항목이 포함되어 있습니다. 기사 초안을 다시 확인해 주세요.")
    values = {}
    selected_domestic: list[tuple[str, dict[str, Any]]] = []
    for key in ARTICLE_SLOT_KEYS:
        if key not in sections:
            values[key] = ("", None)
            continue
        section = sections[key]
        if not isinstance(section, dict):
            raise ArticleHwpxError("기사 초안 항목의 형식이 올바르지 않습니다.")
        status = section.get("status")
        if isinstance(status, str) and status in _BLANK_STATUSES:
            values[key] = ("", None)
            continue
        if status != "completed":
            raise ArticleHwpxError("기사 초안 작업이 완료된 뒤 한글파일에 반영해 주세요.")
        raw_summary = section.get("summary")
        if raw_summary is None or (isinstance(raw_summary, str) and not raw_summary.strip()):
            values[key] = ("", None)
            continue
        summary = _clean(section.get("summary"), limit=SUMMARY_LIMITS[key], label="기사 요약")
        if len(summary) < SUMMARY_MIN_LENGTH:
            raise ArticleHwpxError("기사 요약은 40자 이상이어야 합니다.")
        summary = normalize_report_spacing(summary)
        citation = None
        if key == "domestic" or key.startswith("domestic_"):
            article = section.get("article")
            if not isinstance(article, dict):
                raise ArticleHwpxError("국내기사의 제목·매체·날짜 정보가 필요합니다.")
            title = _clean(article.get("title"), limit=350, label="국내기사 제목")
            publisher = _clean(article.get("publisher"), limit=100, label="국내기사 매체")
            publisher = normalize_article_publisher(publisher, title=title, url=article.get("url", ""))
            title = clean_article_title(title, publisher, url=article.get("url", ""))
            title = format_domestic_article_title(title)
            identity = {**article, 'title': title, 'publisher': publisher}
            for previous_key, previous in selected_domestic:
                if _same_domestic_article(previous, identity):
                    raise ArticleHwpxError(
                        f"{SECTION_AUDIENCES[previous_key]}와 {SECTION_AUDIENCES[key]}에 같은 기사가 있습니다. "
                        "기사 초안을 다시 작성해 중복되지 않은 원문을 선택해 주세요.")
            selected_domestic.append((key, identity))
            try:
                published = date.fromisoformat(article.get("publishedDate", ""))
            except (ValueError, TypeError) as error:
                raise ArticleHwpxError("국내기사의 발행일을 확인해 주세요.") from error
            citation = f"“{title}”({publisher},{published.month}.{published.day}.)"
        values[key] = (summary, citation)
    if not any(summary for summary, _ in values.values()):
        raise ArticleHwpxError("완료된 기사 요약이 최소 1개 필요합니다. 기사 초안을 먼저 작성해 주세요.")
    return values


def _text_patches(data: bytes, paragraph: _Node, spans: list[tuple[int, int, str]]) -> tuple[list[tuple[int, int, bytes]], str]:
    """Redistribute each semantic segment over its existing styled text runs."""
    texts = paragraph.texts
    old = paragraph.own_text
    if not texts or spans[0][0] != 0 or spans[-1][1] != len(old):
        raise ArticleHwpxError("기사 문단의 글자 구조를 확인하지 못했습니다.")
    positions = []
    offset = 0
    for text in texts:
        if any(child.name not in (_HP + "fwSpace", _HP + "tab", _HP + "lineBreak") for child in text.children):
            raise ArticleHwpxError("기사 문단에 지원하지 않는 글자 개체가 있습니다.")
        positions.append((offset, offset + len(text.text)))
        offset += len(text.text)
    rewritten = ["" for _ in texts]
    for start, end, new in spans:
        if end < start:
            raise ArticleHwpxError("기사 문단을 안전하게 적용할 수 없습니다.")
        if end == start:
            target = next((index for index, (left, right) in enumerate(positions) if left <= start <= right), 0)
            rewritten[target] += new
            continue
        for index, (left, right) in enumerate(positions):
            a, b = max(start, left), min(end, right)
            if a < b:
                rewritten[index] += new[(a - start) * len(new) // (end - start):(b - start) * len(new) // (end - start)]
    expected = "".join(value for _, _, value in spans)
    if "".join(rewritten) != expected:
        raise ArticleHwpxError("기사 문구를 글자 서식에 맞춰 적용하지 못했습니다.")
    patches = []
    for node, new in zip(texts, rewritten):
        encoded = escape(new).encode("utf-8")
        if node.empty:
            if new:
                tag = data[node.start:node.open_end]
                qname = re.match(br"<([^\s/>]+)", tag)[1]
                patches.append((node.start, node.end, re.sub(br"/\s*>\Z", b">", tag) + encoded + b"</" + qname + b">"))
        else:
            patches.append((node.open_end, node.close_start, encoded))
    patches.extend((node.start, node.end, b"") for node in paragraph.children if node.name == _HP + "linesegarray")
    return patches, expected


def _apply_patches(data: bytes, patches: list[tuple[int, int, bytes]]) -> bytes:
    ordered = sorted(patches, key=lambda patch: (patch[0], patch[1]))
    previous = 0
    chunks = []
    for start, end, value in ordered:
        if start < previous:
            raise ArticleHwpxError("기사 적용 위치가 겹쳐서 작업을 중단했습니다.")
        chunks.extend((data[previous:start], value))
        previous = end
    chunks.append(data[previous:])
    return b"".join(chunks)


def _article_width(paragraph: _Node, *, domestic: bool) -> int:
    cell = paragraph.ancestor(_HP + "tc")
    if cell is not None:
        size = next((node for node in cell.children if node.name == _HP + "cellSz"), None)
        margin = next((node for node in cell.children if node.name == _HP + "cellMargin"), None)
        if size is not None:
            try:
                width = int(size.attributes["width"])
                if margin is not None:
                    width -= int(margin.attributes.get("left", "0")) + int(margin.attributes.get("right", "0"))
                if width > 0:
                    return width
            except (ValueError, KeyError):
                pass
    return 46604 if domestic else 46320


def _styled_paragraph_patches(data: bytes, paragraph: _Node, text: str,
                              styles: ArticleLayoutStyles, kind: str, *, section_key: str | None = None) -> tuple[list, dict]:
    runs = [node for node in paragraph.children if node.name == _HP + "run" and
            any(child.name == _HP + "t" for child in node.children)]
    if not runs or any(child.name != _HP + "t" for run in runs for child in run.children):
        raise ArticleHwpxError("기사 문단에 지원하지 않는 글자 개체가 있습니다.")
    qname = re.match(br"<([^\s/>]+)", data[runs[0].start:runs[0].open_end])[1].decode("ascii")
    prefix = qname.split(":", 1)[0]
    rendered, layout = styles.build_runs(text, kind=kind, paragraph_prefix=prefix,
                                        available_width=_article_width(paragraph, domestic=kind != "local"),
                                        max_lines=summary_line_limit(section_key) if section_key else None)
    if not layout['withinLineLimit']:
        label = SECTION_AUDIENCES[section_key] if section_key else "기사 요약"
        raise ArticleHwpxError(f"{label} 요약이 허용된 {layout['allowedLines']}줄에 들어가지 않습니다. "
                               f"자간 {MAX_ARTICLE_TRACKING}에서도 넘치는 문구는 수치·조건을 보존해 더 간결하게 요약한 뒤 적용해 주세요.")
    patches = [(runs[0].start, runs[0].end, rendered)]
    patches.extend((node.start, node.end, b"") for node in runs[1:])
    # Empty trailing runs from old manual edits can carry obsolete -20/-31
    # spacing into subsequent typing. They contain no text or document object.
    patches.extend((node.start, node.end, b"") for node in paragraph.children
                   if node.name == _HP + "run" and not node.children and not node.text.strip())
    patches.extend((node.start, node.end, b"") for node in paragraph.children if node.name == _HP + "linesegarray")
    old_id = paragraph.attributes.get('paraPrIDRef', '')
    new_id = old_id
    if kind in ('local', 'domestic') and not layout['oneLine']:
        marker = re.match(r'^\s*[-−–]\s*', text)
        if marker is None:
            raise ArticleHwpxError("기사 줄맞춤의 시작 기호를 확인하지 못했습니다.")
        prefix_width = styles.marker_prefix_width(
            text, kind=kind, marker_length=marker.end(),
            available_width=_article_width(paragraph, domestic=kind != 'local'),
            paragraph_style_id=old_id, tracking=int(layout['tracking']),
        )
        new_id = styles.hanging_paragraph_style(old_id, prefix_width)
        layout['hangingIndentPt'] = round(prefix_width, 2)
        layout['wrappedLineAnchor'] = 'local-label-start' if kind == 'local' else 'summary-start'
        if kind == 'local':
            new_id = styles.word_safe_paragraph_style(new_id)
    if new_id != old_id:
        opening = data[paragraph.start:paragraph.open_end]
        pattern = br'(\bparaPrIDRef\s*=\s*)([\'\"])[^\'\"]*\2'
        if not re.search(pattern, opening):
            raise ArticleHwpxError("기사 줄맞춤의 문단 속성 번호를 확인하지 못했습니다.")
        changed = re.sub(pattern, lambda match: match[1] + match[2] + new_id.encode() + match[2], opening, count=1)
        patches.append((paragraph.start, paragraph.open_end, changed))
    return patches, layout


def _page_group_patches(parts: dict[str, bytes]) -> dict[str, list]:
    """Keep the original second-page report heading, not a second extra break."""
    top = []
    for name, data in parts.items():
        root, _ = _parse_section(data)
        top.extend((name, node) for node in root.children if node.name == _HP + "p")
    chicken = next((index for index, (_, node) in enumerate(top)
                    if _normalized(node.own_text) in ("□육계수급및가격동향", "□닭고기수급및가격동향")), None)
    if chicken is None:
        raise ArticleHwpxError("육계·계란의 두 번째 페이지 시작 위치를 확인하지 못했습니다.")
    # In the supplied layout the previous paragraph contains the second page's
    # report title table and owns its existing break. Preserve that boundary.
    boundary = chicken
    if chicken > 0:
        previous = top[chicken - 1][1]
        if "주간 해외 축산물 수급 및 가격 동향" in previous.text:
            boundary = chicken - 1
    patches = {name: [] for name in parts}
    for index, (name, paragraph) in enumerate(top):
        desired = "1" if index == boundary else "0"
        if paragraph.attributes.get("pageBreak", "0") == desired:
            continue
        tag = parts[name][paragraph.start:paragraph.open_end]
        expression = br"(\bpageBreak\s*=\s*)(['\"])[^'\"]*\2"
        if re.search(expression, tag):
            tag = re.sub(expression, lambda match: match[1] + match[2] + desired.encode() + match[2], tag, count=1)
        else:
            tag = tag[:-1] + b' pageBreak="' + desired.encode() + b'">'
        patches[name].append((paragraph.start, paragraph.open_end, tag))
    return patches


def _reuse_article_character_styles(parts: dict[str, bytes], header: bytes,
                                   original_header: bytes) -> tuple[dict[str, bytes], bytes]:
    """Reuse equivalent charPr clones so identical reapplication is stable.

    Only freshly appended article styles can be removed or remapped. Existing
    shared styles and their references remain byte-identical; the header is
    patched by spans rather than reserialized.
    """
    namespace = "{http://www.hancom.co.kr/hwpml/2011/head}"
    originals = {node.get('id') for node in ET.fromstring(original_header).iter(namespace + 'charPr')}

    def signature(node, *, style_root=False):
        attributes = tuple(sorted((key, value) for key, value in node.attrib.items()
                                  if not (style_root and key == 'id')))
        return node.tag, attributes, node.text or '', tuple(signature(child) for child in node)

    existing = {}
    aliases = {}
    for node in ET.fromstring(header).iter(namespace + 'charPr'):
        identity = node.get('id')
        spec = signature(node, style_root=True)
        if identity in originals:
            existing.setdefault(spec, identity)
        elif spec in existing:
            aliases[identity] = existing[spec]
        else:
            existing[spec] = identity
    if not aliases:
        return parts, header
    patches = []
    for match in re.finditer(rb'<(?P<prefix>[A-Za-z_][\w.-]*):charPr\b[^>]*(?:/>|>.*?</(?P=prefix):charPr\s*>)', header, re.S):
        identity = re.search(br'\bid\s*=\s*([\'\"])(\d+)\1', match[0])
        if identity and identity[2].decode() in aliases:
            patches.append((match.start(), match.end(), b''))
    container = re.search(rb'<[A-Za-z_][\w.-]*:charProperties\b[^>]*>', header)
    count = re.search(br'\bitemCnt\s*=\s*([\'\"])(\d+)\1', container[0]) if container else None
    if count is None or len(patches) != len(aliases):
        raise ArticleHwpxError("기사 글자 속성의 재사용 검증에 실패했습니다.")
    new_count = str(int(count[2]) - len(aliases)).encode()
    opening = container[0][:count.start(2)] + new_count + container[0][count.end(2):]
    patches.append((container.start(), container.end(), opening))
    header = _apply_patches(header, patches)
    # Scan complete quoted attributes, not matching text inside another value.
    expression = br'(?P<name>[A-Za-z_][\w:.-]*)\s*=\s*(?P<quote>[\'\"])(?P<value>.*?)(?P=quote)'
    edited = {}
    for name, data in parts.items():
        root, _ = _parse_section(data)
        references = []
        nodes = [root]
        while nodes:
            node = nodes.pop()
            nodes.extend(node.children)
            identity = node.attributes.get('charPrIDRef') if node.name == _HP + 'run' else None
            if identity not in aliases:
                continue
            opening = data[node.start:node.open_end]
            attributes = [match for match in re.finditer(expression, opening, re.S)
                          if match['name'] == b'charPrIDRef']
            if len(attributes) != 1 or attributes[0]['value'] != identity.encode():
                raise ArticleHwpxError("기사 글자 속성 참조의 재사용 검증에 실패했습니다.")
            attribute = attributes[0]
            opening = (opening[:attribute.start('value')] + aliases[identity].encode()
                       + opening[attribute.end('value'):])
            references.append((node.start, node.open_end, opening))
        edited[name] = _apply_patches(data, references)
    return edited, header


def _edit_sections(parts: dict[str, bytes], values: dict[str, tuple[str, str | None]],
                   header: bytes) -> tuple[dict[str, bytes], bytes, dict[str, dict]]:
    from src.overseas_article_digest import compact_report_summary

    slots = _discover_slots(parts)
    style_ids = lambda title, domestic: [run.attributes.get("charPrIDRef", "")
        for slot in slots.values() if (slot.title is not None) == domestic
        for paragraph in ([slot.title] if title else [slot.paragraph]) if paragraph is not None
        for run in paragraph.children if run.name == _HP + "run"]
    styles = ArticleLayoutStyles(header, local_style_ids=style_ids(False, False),
                                 domestic_style_ids=style_ids(False, True), title_style_ids=style_ids(True, True))
    patches = _page_group_patches(parts)
    layouts = {}
    for key, slot in slots.items():
        summary, citation = values[key]
        old = slot.paragraph.own_text
        prefix = (_LOCAL_PREFIX if slot.title is None else _SUMMARY_PREFIX).fullmatch(old)
        if prefix is None:
            raise ArticleHwpxError("기사 문단의 시작 기호를 확인하지 못했습니다.")
        new_prefix = " - (현지동향) " if slot.title is None else " - "
        kind = "local" if slot.title is None else "domestic"
        width = _article_width(slot.paragraph, domestic=kind != "local") / 100
        natural_width = styles.estimate_width(new_prefix + summary, kind=kind)
        original_summary = summary
        # Try lossless, known single-statistic contractions before spacing.
        # Unknown/complex wording stays unchanged and gets natural wrapping.
        if natural_width > width:
            summary = compact_report_summary(summary, key, target=40)
            values[key] = (summary, citation)
        change, layout = _styled_paragraph_patches(parts[slot.section], slot.paragraph, new_prefix + summary,
                                                  styles, kind, section_key=key)
        layout["summaryAdjusted"] = summary != original_summary
        layout["renderedSummary"] = summary
        layout["blank"] = not bool(summary)
        patches[slot.section].extend(change)
        layouts[key] = layout
        # A former manually wrapped continuation must not leave a blank line.
        patches[slot.section].extend((paragraph.start, paragraph.end, b"") for paragraph in slot.continuations)
        if slot.title is not None:
            match = _TITLE.fullmatch(slot.title.own_text)
            assert match is not None
            change, title_layout = _styled_paragraph_patches(parts[slot.section], slot.title, "∙" + (citation or ""),
                                                            styles, "title")
            patches[slot.section].extend(change)
            layouts[key]["title"] = title_layout
    edited = {name: _canonical_namespaces(_apply_patches(data, patches[name])) for name, data in parts.items()}
    verified = _discover_slots(edited)
    for key, slot in verified.items():
        summary, citation = values[key]
        match = (_LOCAL_PREFIX if slot.title is None else _SUMMARY_PREFIX).fullmatch(slot.paragraph.own_text)
        actual = (match[2] if match else "") + "".join(node.own_text for node in slot.continuations)
        if actual != summary or (slot.title is not None and slot.title.own_text != "∙" + (citation or "")):
            raise ArticleHwpxError("저장 후 기사 문구 검증에 실패했습니다.")
        if any(node.name == _HP + "linesegarray" for paragraph in [slot.paragraph, *slot.continuations, *([slot.title] if slot.title else [])] for node in paragraph.children):
            raise ArticleHwpxError("기사 문단의 줄 배치 정보를 갱신하지 못했습니다.")
    edited, edited_header = _reuse_article_character_styles(edited, styles.patched_header(), header)
    return edited, edited_header, layouts


def _read_package(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes], bytes]:
    if not path.is_file() or path.stat().st_size > _MAX_ARCHIVE:
        raise ArticleHwpxError("40MB 이하의 HWPX 한글파일을 넣어 주세요.")
    try:
        with zipfile.ZipFile(path, "r") as package:
            entries = package.infolist()
            if len(entries) > _MAX_ENTRIES or sum(entry.file_size for entry in entries) > _MAX_EXPANDED:
                raise ArticleHwpxError("한글파일의 압축 해제 크기가 너무 큽니다.")
            names = [entry.filename for entry in entries]
            if len(set(names)) != len(names):
                raise ArticleHwpxError("중복된 파일 항목이 포함된 한글파일은 사용할 수 없습니다.")
            data = {}
            for entry in entries:
                name = entry.filename
                original_name = entry.orig_filename
                relative = PurePosixPath(original_name)
                if (not name or "\\" in original_name or ":" in original_name or "\x00" in original_name or relative.is_absolute() or ".." in relative.parts
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ArticleHwpxError("안전하지 않은 파일 항목이 포함된 한글파일입니다.")
                if entry.flag_bits & 1 or entry.file_size > _MAX_MEMBER or entry.file_size > max(entry.compress_size, 1) * 200:
                    raise ArticleHwpxError("암호화되었거나 과도하게 압축된 한글파일은 사용할 수 없습니다.")
                payload = package.read(entry)
                if name.endswith((".xml", ".hpf")) and re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, re.I):
                    raise ArticleHwpxError("외부 엔터티가 포함된 한글파일은 사용할 수 없습니다.")
                data[name] = payload
            if data.get("mimetype", b"").strip() != b"application/hwp+zip" or "Contents/header.xml" not in data:
                raise ArticleHwpxError("올바른 HWPX 한글파일을 넣어 주세요. HWP 파일은 지원하지 않습니다.")
            if not any(_SECTION_NAME.fullmatch(name) for name in data):
                raise ArticleHwpxError("한글파일에서 본문을 찾지 못했습니다.")
            return entries, data, package.comment
    except ArticleHwpxError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as error:
        raise ArticleHwpxError("HWPX 한글파일을 읽지 못했습니다. 파일이 손상되었거나 암호화되어 있는지 확인해 주세요.") from error


def apply_article_draft_to_hwpx(input_path: Path, output_path: Path, draft: dict[str, Any]) -> dict[str, Any]:
    """Apply finished briefs and clear unfinished slots in the uploaded copy."""
    input_path, output_path = Path(input_path), Path(output_path)
    if input_path.resolve() == output_path.resolve() or output_path.exists():
        raise ArticleHwpxError("원본파일을 덮어쓸 수 없습니다. 새 결과 파일 경로를 사용해 주세요.")
    values = _draft_values(draft)
    entries, members, comment = _read_package(input_path)
    sections = {name: data for name, data in members.items() if _SECTION_NAME.fullmatch(name)}
    try:
        edited, edited_header, layouts = _edit_sections(sections, values, members["Contents/header.xml"])
    except ArticleLayoutError as error:
        raise ArticleHwpxError(str(error)) from error
    edited["Contents/header.xml"] = edited_header
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    created = False
    try:
        with tempfile.NamedTemporaryFile(prefix=".article_hwpx_", suffix=".tmp", dir=output_path.parent, delete=False) as holder:
            temporary = Path(holder.name)
        with zipfile.ZipFile(temporary, "w") as result:
            result.comment = comment
            for entry in entries:
                result.writestr(entry, edited.get(entry.filename, members[entry.filename]))
        with zipfile.ZipFile(temporary) as result:
            if result.testzip() is not None:
                raise ArticleHwpxError("결과 한글파일의 압축 검증에 실패했습니다.")
        # Exclusive creation prevents overwriting a user file, even if it appeared
        # after the earlier existence check. The API publishes only after return.
        with output_path.open("xb") as target:
            created = True
            with temporary.open("rb") as source:
                shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    except ArticleHwpxError:
        if created:
            output_path.unlink(missing_ok=True)
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if created:
            output_path.unlink(missing_ok=True)
        raise ArticleHwpxError("기사 반영 한글파일을 저장하지 못했습니다. 다시 시도해 주세요.") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    applied = [key for key in ARTICLE_SLOT_KEYS if values[key][0]]
    blank = [key for key in ARTICLE_SLOT_KEYS if not values[key][0]]
    domestic = [key for key in applied if key == "domestic" or key.startswith("domestic_")]
    return {"appliedCount": len(applied), "localCount": len(applied) - len(domestic), "domesticCount": len(domestic),
            "blankCount": len(blank), "blankSlots": blank, "slots": list(ARTICLE_SLOT_KEYS),
            "layout": layouts, "layoutMeasurement": "estimate-not-rendered"}
