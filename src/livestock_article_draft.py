"""Twelve weekly market briefs: preferred publishers, then public news search.

Only dated, publicly readable original articles are summarized. Search snippets
are discovery aids, never evidence. No login, browser impersonation, paywall
bypass or paid search/LLM service is used. Each section can fail independently.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import json
from itertools import chain
import re
from threading import Event, Lock
from time import monotonic
from typing import Any, Callable
import unicodedata
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from . import overseas_article_digest as source
from .report_brief_style import EDITORIAL_TOPICS, MARKET_CONTEXT_SECTIONS, STYLE_VERSION
from .runtime_cache import ttl_cache
from .report_reference_corpus import cited_media_queries
from .article_cancellation import (
    ArticleDraftCancelled, article_cancellation_scope, cancellation_checkpoint,
    cancellable_lock, check_article_cancelled, map_article_tasks, submit_article_task,
)


class SourceUnavailable(source.ArticleDigestError):
    """A safe, credential-free availability message for the article UI."""


SPECIES_TERMS = {
    "beef": ("소고기", "쇠고기", "육우", "beef", "cattle", "calves", "veal"),
    "pork": ("돼지", "돼지고기", "돈육", "양돈", "pork", "pig", "pigs", "hog", "hogs", "swine", "豚肉", "suíno", "suínos", "suína", "suinocultura", "Schlachtschweine", "Schweine", "Schweinemarkt", "Schweinefleisch", "Schweinebörse", "Ferkel"),
    "chicken": ("닭고기", "육계", "닭", "치킨", "가금육", "가금류", "삼계탕", "chicken", "chickens", "broiler", "broilers", "poultry", "frango", "frangos", "avicultura"),
    "egg": ("계란", "달걀", "산란계", "egg", "eggs", "layer", "layers", "ovos", "ovo", "鶏卵", "卵", "たまご", "タマゴ", "採卵"),
}
FOREIGN_TERMS = ("미국", "호주", "브라질", "유럽", "독일", "일본", "중국", "해외", "EU", "USDA",
                 "북한", "베트남", "이란", "태국", "싱가포르", "아르헨티나", "벨라루스", "칠레", "덴마크",
                 "영국", "프랑스", "캐나다", "홍콩", "대만", "네덜란드", "스페인", "멕시코", "뉴질랜드",
                 "러시아", "인도", "필리핀", "인도네시아", "튀르키예", "말레이시아", "이탈리아", "아일랜드",
                 "벨기에", "美", "日", "中", "北", "英")
MARKET_TERMS = source.MARKET_TERMS + (
    "수요", "물가", "수송", "운송", "소비", "감염", "살처분", "부족", "품귀", "인플루엔자", "독감",
    "demand", "inflation", "retail", "consumption", "inventory", "tariff", "disease", "bird flu", "shortage", "hatch", "placements", "incubation",
    "prices", "supplies", "imports", "exports", "inventories", "tariffs", "slaughtered", "production",
    "preço", "preços", "produção", "exportação", "exportações", "oferta", "demanda", "abate", "consumo", "inflação", "gripe",
    "価格", "相場", "供給", "生産", "輸出", "輸入", "需要", "飼料", "物価", "不足", "鳥インフルエンザ", "出荷", "消費", "trade", "quotação", "retomar", "compra",
    "배송", "운송비", "항공", "유통구조", "검역", "살모넬라", "회수", "리콜", "가공비", "사료비", "food safety", "distribution", "logistics",
    "Angebot", "Bedarf", "Fleischmarkt", "Preisen", "Preise", "Nachfrage", "Umsätze", "Produktion", "Export", "Import",
)
NON_MARKET_TERMS = (
    "레시피", "맛집", "행사", "박람회", "자료집", "등급제", "발간", "협약", "프로모션",
    "recipe", "recipes", "anniversary", "award", "sponsorship", "webinar", "expo", "conference",
    "レシピ", "キャンペーン", "フェア", "監修", "新商品", "新発売", "発行のお知らせ", "receita", "aniversário", "한자리에", "워크숍", "간담회", "총회", "전국 육계인",
    "industry exchange", "industry cooperation forum", "trade mission",
)
# User posts can mention Japan/eggs while describing a Taiwanese acquisition.
# They are not local editorial news or a public market report.
USER_POST_HOSTS = ("note.com", "ameblo.jp", "blog.naver.com", "tistory.com", "medium.com")
JAPANESE_LOCAL_NEWS_HOSTS = ("times.abema.tv", "news.tv-asahi.co.jp", "news.ntv.co.jp", "www3.nhk.or.jp", "www.agrinews.co.jp", "www.fnn.jp")
GERMAN_PORK_REPORT_URL = "https://www.lwk-rlp.de/markt-statistik/marktbericht/marktbericht/schlachtschweine"
JAPANESE_EGG_MARKET_URL = "https://www.jz-tamago.co.jp/business/souba/"
# Public RSS output of ABPA's news search, independent of any article/week.
ABPA_CHICKEN_NEWS_FEED_URL = "https://abpa-br.org/?" + urlencode({"post_type": "post", "s": "frango", "feed": "rss2"})
USDA_DAILY_REPORTS = {
    "us_egg": ("https://www.ams.usda.gov/mnreports/ams_2843.pdf", "Daily National Shell Egg Index Report"),
    "us_chicken": ("https://www.ams.usda.gov/mnreports/ams_2740.pdf", "Daily National Broiler Market-At-A-Glance"),
}
USDA_PUBLIC_ARCHIVE_URL = "https://mymarketnews.ams.usda.gov/filerepo/reports"
USDA_ARCHIVE_TIMEOUT_SECONDS = 5


def _domestic_overseas_focus(article: dict[str, Any], spec: SectionSpec) -> bool:
    title = str(article.get("title", ""))
    body = str(article.get("body", ""))
    # Imported meat sold in a Korean supermarket is still a domestic retail
    # promotion, not news about the exporting country's market. Check this
    # BEFORE accepting an overseas country name in the headline.
    if re.search(r"서울고법|공정위|집행정지|산란계협회|한돈|육우자조금|군\s*급식|셰프|Cooking&Food|이마트|홈플러스|롯데마트|차례상|명절선물|장보기|먹거리\s*할인", title, re.I):
        return False
    if re.search(r"매각|인수|투자", title) and re.search(r"노랑통닭|교촌|BBQ|BHC|프랜차이즈|K치킨|치킨\s*브랜드", title, re.I):
        return False
    if (spec.species == "chicken" and re.search(r"가맹점|본사|프랜차이즈|교촌|BBQ|BHC|가라아게|치킨\s*브랜드", title, re.I)
            and not re.search(r"닭고기|육계|가금육|원료육", title)):
        return False  # restaurant expansion/retail disputes are not poultry supply news
    if re.search(r"증시|나스닥|코스피|주식|채권|주가|투자\s*수익|증권|펀드|오늘의\s*신문|년\s*전\s*오늘|태극기|연예|화보|사칭\s*계정|스타이슈|국빈만찬|국빈\s*만찬|평화의\s*건배|감량|다이어트|단백질\s*보충제|스마트\s*안경|AI\s*안경|불닭|치킨게임", title, re.I):
        return False
    if not _has_terms(title, SPECIES_TERMS[spec.species]) and re.search(
        r"가계\s*자산|자산\s*(?:격차|불평등)|부의\s*불평등|상위\s*\d+\s*%|"
        r"K[-·\s]?(?:브랜드|뷰티|푸드)|비비고|(?:만두|라면).*(?:대박|비결)|"
        r"수출\s*(?:\d+\s*조|1\s*조)\s*달러", title, re.I,
    ):
        return False  # a passing meat-price/ingredient mention is not the story's subject
    if re.search(r"수출", title) and re.search(r"농협|국산|한국산|제주(?:산)?|한돈|지자체", title):
        # Domestic producer sales milestones do not describe the destination's
        # livestock market. Retain trade changes that explicitly affect that
        # market's supply, price, food safety or border policy.
        foreign_market_impact = any(
            _has_terms(sentence, FOREIGN_TERMS)
            and _has_terms(sentence, SPECIES_TERMS[spec.species])
            and re.search(r"(?:가격|공급\s*(?:부족|물량.{0,12}(?:확대|증가))|수급\s*(?:불안|안정)|생산량|소비량|검역|관세|살처분|수입\s*(?:금지|중단|재개))", sentence)
            for sentence in re.split(r"(?<=[.!?。])\s+|\n+", body[:7000])
        )
        if not foreign_market_impact:
            return False
    if "국내" in title and not re.search(r"수입|수출|교역|검역|운송|배송", title):
        return False
    if (re.search(r"지방소멸|소득원|지역\s*특화|기능성\s*계란|농가\s*육성", title)
            and not _has_terms(title, FOREIGN_TERMS) and not re.search(r"수입|수출|교역", title)):
        return False  # local development/product stories are not overseas egg markets
    if re.search(r"소비자\s*물가|\bCPI\b|물가.{0,20}\d+(?:\.\d+)?\s*%", title, re.I) and not _has_terms(title, FOREIGN_TERMS):
        return False  # Korean CPI + imported beef is not overseas pork news
    if (not _has_terms(title, FOREIGN_TERMS) and not re.search(r"수입|수출|교역|해외", title)
            and re.search(r"산란계협회", body[:1800]) and re.search(r"공정거래|공정위|과징금|집행정지", body[:1800])):
        return False  # an overseas comparison does not turn a Korean legal case into overseas egg news
    # The user's reports include foreign trade, food safety, consumer demand and
    # egg logistics. Require an actual species+market passage, but search the
    # WHOLE article instead of only its first 800 characters/four sentences.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|(?<=。)|\n+", body[:7000]) if len(s.strip()) >= 12]
    title_foreign = _has_terms(title, FOREIGN_TERMS)
    for index, sentence in enumerate(sentences):
        if not _has_terms(sentence, SPECIES_TERMS[spec.species]) or not _has_terms(sentence, MARKET_TERMS):
            continue
        if (spec.species == 'egg' and re.search(r"원료|재료|성분", sentence)
                and re.search(r"육류|유제품", sentence)
                and not re.search(r"(?:계란|달걀).{0,12}(?:가격|수급|생산|공급|수요|운송|수입량|수출량|검역)", sentence)):
            continue  # an ingredient list in a K-food story is not egg-market news
        # A neighbouring imported BEEF statistic must not qualify domestic
        # pork/egg/chicken inflation. Tie trade language to this species in
        # the same clause, rather than borrowing another commodity's context.
        clauses = re.split(r"[,，;；]|(?:인\s*반면|하지만|그러나)", sentence)
        species_trade = any(
            _has_terms(clause, SPECIES_TERMS[spec.species])
            and re.search(r"수입|수출|국제\s*(?:운송|교역)|해외\s*배송", clause)
            and not re.search(r"수입.{0,40}(?:보다|대신)", clause)
            and not any(_has_terms(clause, terms) for name, terms in SPECIES_TERMS.items() if name != spec.species)
            for clause in clauses
        )
        previous = sentences[index - 1] if index else ""
        country_context = _has_terms(sentence, FOREIGN_TERMS) or (
            _has_terms(previous, FOREIGN_TERMS) and _has_terms(previous, SPECIES_TERMS[spec.species])
        )
        if title_foreign or country_context or species_trade or (
            re.search(r"CPTPP|FTA", title + ' ' + sentence) and re.search(r"수입|수출|교역", sentence)
        ):
            return True
    return False
EU_REGIONS = ("Germany", "German", "Deutschland", "European Union", "Europe", "European", "EU",
              "France", "French", "Spain", "Spanish", "Denmark", "Danish", "Netherlands", "Dutch", "Poland", "Polish", "Italy", "Italian", "Belgium", "Belgian", "Austria", "독일", "유럽")


@dataclass(frozen=True)
class SectionSpec:
    key: str
    label: str
    species: str
    country: str
    language: str
    publisher: str
    listings: tuple[str, ...]
    queries: tuple[str, ...]
    regions: tuple[str, ...]
    domestic: bool = False


SECTION_SPECS = (
    SectionSpec("us", "소 - 미국", "beef", "US", "en", "USMEF 뉴스라인", (),
                ("United States beef supply prices cattle", "US beef imports demand"), ("United States", "U.S.", "US", "American", "미국")),
    SectionSpec("australia", "소 - 호주", "beef", "AU", "en", "MLA Latest News", (),
                ("Australia cattle beef supply prices", "Australian beef exports market"), ("Australia", "Australian", "호주")),
    SectionSpec("domestic", "소 - 국내기사", "beef", "KR", "ko", "네이버 뉴스", (),
                ("미국 소고기", "호주 쇠고기", "브라질 소고기"), FOREIGN_TERMS, True),
    SectionSpec("us_pork", "돼지 - 미국", "pork", "US", "en", "USMEF 뉴스라인", (),
                ("United States pork hog supply prices", "US pork exports production"), ("United States", "U.S.", "US", "American", "미국")),
    SectionSpec("eu_pork", "돼지 - EU(독일)", "pork", "DE", "en", "EuroMeatNews",
                ("https://euromeatnews.com/", "https://euromeatnews.com/category/retail/", "https://euromeatnews.com/category/industry/", "https://euromeatnews.com/category/market/"),
                ("Germany pork pig prices supply", "European Union pork retail production"), EU_REGIONS),
    SectionSpec("domestic_pork", "돼지 - 국내기사", "pork", "KR", "ko", "네이버 뉴스", (),
                ("미국 돼지고기", "독일 돼지고기", "유럽 돼지고기"), FOREIGN_TERMS, True),
    SectionSpec("us_chicken", "닭 - 미국", "chicken", "US", "en", "Brownfield Ag News",
                ("https://www.brownfieldagnews.com/news/", "https://www.brownfieldagnews.com/?s=chicken", "https://www.brownfieldagnews.com/?s=poultry"),
                ("United States chicken broiler prices production", "US chicken supply poultry exports"), ("United States", "U.S.", "US", "American", "미국")),
    SectionSpec("brazil_chicken", "닭 - 브라질", "chicken", "BR", "pt", "AviSite",
                ("https://www.avisite.com.br/",),
                ("Brasil frango preço produção exportações", "Brasil carne de frango oferta demanda"), ("Brasil", "Brazil", "brasileiro", "brasileira", "브라질")),
    SectionSpec("domestic_chicken", "닭 - 국내기사", "chicken", "KR", "ko", "네이버 뉴스", (),
                ("미국 닭고기", "브라질 닭고기", "해외 육계"), FOREIGN_TERMS, True),
    SectionSpec("us_egg", "계란 - 미국", "egg", "US", "en", "Brownfield Ag News",
                ("https://www.brownfieldagnews.com/news/", "https://www.brownfieldagnews.com/?s=eggs"),
                ("United States egg prices supply production", "US eggs shortage bird flu"), ("United States", "U.S.", "US", "American", "미국")),
    SectionSpec("japan_egg", "계란 - 일본", "egg", "JP", "ja", "JA 전농·전농타마고",
                ("https://www.zennoh.or.jp/press/release/index.html", "https://www.jz-tamago.co.jp/news/"),
                ("日本 鶏卵 価格 供給 生産", "日本 卵 相場 鳥インフルエンザ"), ("日本", "Japan", "일본")),
    SectionSpec("domestic_egg", "계란 - 국내기사", "egg", "KR", "ko", "네이버 뉴스", (),
                ("미국 계란", "일본 달걀", "해외 계란"), FOREIGN_TERMS, True),
)
SPECS_BY_KEY = {spec.key: spec for spec in SECTION_SPECS}
SECTION_GROUPS = tuple({"label": label, "sections": tuple(spec for spec in SECTION_SPECS if spec.species == species)}
                       for species, label in (("beef", "소고기"), ("pork", "돼지고기"), ("chicken", "닭고기"), ("egg", "계란")))

# Short, different discovery queries instead of requiring every market keyword
# at once. Dates are ALWAYS checked on the returned original, never relaxed.
SEARCH_QUERIES = {
    "us": ("US beef prices", "US cattle supply"),
    "australia": ("Australia cattle", "Australian beef exports"),
    "us_pork": ("US pork", "US hog prices"),
    "eu_pork": ("Germany pork", "EU pig prices"),
    "us_chicken": ("US broiler production", "US chicken prices"),
    "brazil_chicken": ("Brasil frango", "frango exportações"),
    "us_egg": ("egg prices America", "US egg production"),
    "japan_egg": ("鶏卵 価格", "卵 供給 日本", "卵 最高値"),
    "domestic": ("미국 쇠고기 가격", "호주 소고기 수출", "해외 소고기 가격", "브라질 쇠고기"),
    "domestic_pork": ("돼지고기 가격", "브라질 돼지고기 수입", "돈육 수급", "돼지고기 관세", "돼지고기 수출"),
    "domestic_chicken": ("닭고기 수입", "닭고기 가격", "닭고기 소비", "닭고기 리콜", "닭고기 수입 안전", "가금육 수출"),
    "domestic_egg": ("달걀 수입", "계란 가격", "계란 운송", "계란 공급"),
}

# Discovery only: each selected original must still establish its own country,
# commodity and Sunday-Saturday publication date. These are organizations
# observed in the report references, not narrative attribution from table notes.
REFERENCE_SOURCE_QUERIES = {
    'us': ('site:ers.usda.gov beef outlook demand', 'site:bls.gov beef consumer prices'),
    'australia': ('site:beefcentral.com cattle beef demand market',),
    'us_chicken': ('site:ers.usda.gov broiler poultry outlook',),
    'brazil_chicken': ('site:abpa-br.org frango demanda exportações',),
    'eu_pork': ('site:ahdb.org.uk EU Germany pig market',),
    'japan_egg': ('日本 鶏卵 需給 見通し 農林水産省',),
}


def _has_terms(text: str, terms: tuple[str, ...]) -> int:
    text = text.casefold()
    return sum(bool(re.search(r"(?<![a-z])" + re.escape(term.casefold()) + r"(?![a-z])", text))
               if re.fullmatch(r"[a-zA-Z .]+", term) else term.casefold() in text for term in terms)


def _relevance(article: dict[str, Any], spec: SectionSpec, *, trusted_country: bool = False) -> int:
    title = str(article.get("title", ""))
    lead = f"{title} {str(article.get('body', ''))[:7000]}"
    title_species = _has_terms(title, SPECIES_TERMS[spec.species])
    if (spec.species == "egg" and re.search(r"\bcage[- ]free\b", title, re.I)
            and _has_terms(str(article.get("body", "")), SPECIES_TERMS["egg"])):
        # Local egg-law headlines often say only 'cage-free'. Actual egg
        # evidence in the original body is still required before qualifying.
        title_species += 1
    species = _has_terms(lead, SPECIES_TERMS[spec.species])
    market = _has_terms(lead, MARKET_TERMS)
    region = _has_terms(lead, spec.regions)
    host = urlparse(str(article.get("url", ""))).hostname or ""
    official_germany = spec.key == "eu_pork" and str(article.get("url", "")) == GERMAN_PORK_REPORT_URL
    if official_germany:
        trusted_country = True
    # Local Japanese headlines often omit 'Japan'. Infer local coverage only
    # from an identified editorial publisher, not from any Japanese blog.
    if spec.country == "JP" and host in JAPANESE_LOCAL_NEWS_HOSTS:
        trusted_country = True
    if any(host == domain or host.endswith("." + domain) for domain in USER_POST_HOSTS):
        return -1
    if species == 0 or market == 0 or _has_terms(title, NON_MARKET_TERMS):
        return -1
    if not spec.domestic and re.search(
        r"\b(?:annual meeting|presentations?|research center|experimental|laboratory|colonized)\b",
        lead, re.I,
    ) and re.search(r"\b(?:salmonellosis|prevalence|colonization|microbiolog\w*|pathogen)\b", lead, re.I):
        # A laboratory/meeting report can say 'broiler production' without
        # reporting its market. Retain safety news with an explicit price,
        # supply, trade, recall, or closure consequence.
        if not re.search(
            r"\b(?:prices?|suppl(?:y|ies)|shortage|imports?|exports?|tariffs?|"
            r"inventor(?:y|ies)|recalls?|closures?|slaughter)\b", lead, re.I,
        ):
            return -1
    if not title_species and any(_has_terms(title, terms) for species_name, terms in SPECIES_TERMS.items() if species_name != spec.species):
        return -1
    # A poultry story about laying hens belongs to eggs, not the broiler section.
    if spec.species == "chicken" and _has_terms(title, SPECIES_TERMS["egg"]) and not _has_terms(title, ("chicken", "broiler", "닭고기", "육계", "frango")):
        return -1
    if spec.domestic:
        # A market headline need not spell out the country/species if its lead
        # clearly does. Do not accept domestic-market stories with just a
        # passing imported-product mention buried at the end of the body.
        if not _domestic_overseas_focus(article, spec):
            return -1
        if not title_species:
            # Stock-market recaps/health/shopping articles mentioning an egg or
            # chicken once are not overseas livestock-market stories.
            if re.search(r"증시|나스닥|S&P|FOMC|연준|PCE|다이어트|마트|급식", title, re.I):
                return -1
    elif region == 0:
        if not trusted_country:
            return -1
        # A local publisher can also cover another country's market. Infer its
        # home country only when the headline does not identify a foreign one.
        other_countries = {
            "US": ("Brazil", "Brasil", "China", "Germany", "Japan", "Australia", "Canada", "Mexico", "Europe"),
            "BR": ("Estados Unidos", "China", "Alemanha", "Japão", "Austrália", "Canadá", "México"),
            "JP": ("米国", "アメリカ", "ブラジル", "中国", "豪州", "ドイツ", "メキシコ", "欧州", "ウクライナ"),
        }
        if _has_terms(title, other_countries.get(spec.country, ())):
            return -1
    if not spec.domestic and spec.country == "JP" and not _has_terms(title, spec.regions) and _has_terms(title, ("台湾", "中国", "米国", "ブラジル", "豪州")):
        return -1
    if spec.key == "eu_pork":
        # A British pig-market report mentioning a 'non-EU market' is not EU
        # evidence. Require an affirmative region in an actual market passage.
        region_text = re.sub(r"\b(?:non|outside|former)[- ]EU\b", "", lead, flags=re.I)
        if not _has_terms(region_text, spec.regions) and not official_germany:
            return -1
        non_eu_regions = ("UK", "British", "Britain", "England", "English", "Scotland", "Scottish",
                          "Wales", "Welsh", "Northern Ireland", "Defra", "United States", "U.S.",
                          "USMEF", "Brazil", "Brasil", "China", "Japan", "Canada", "영국")
        if _has_terms(title, non_eu_regions) and not _has_terms(title, spec.regions):
            return -1  # EU competitor prices do not turn a Scottish/US report into EU coverage
        if _has_terms(region_text, non_eu_regions) and not _has_terms(title + ' ' + str(article.get('body', ''))[:700], spec.regions):
            return -1
    if not spec.domestic and title_species == 0 and _has_terms(title, MARKET_TERMS) == 0:
        return -1
    score = min(species, 3) * 4 + min(market, 5) * 3 + min(region, 3) + min(title_species, 2) * 3
    # Price/supply/trade are first choices; consumption, policy, food safety and
    # logistics are meaningful backups observed in the six supplied reports.
    themes = [name for name, terms in EDITORIAL_TOPICS.items() if _has_terms(lead, terms)]
    score += sum(5 if theme in ("price", "supply", "trade") else 2 for theme in themes)
    if spec.domestic and title_species and _has_terms(title, FOREIGN_TERMS):
        score += 14
    if spec.domestic and title_species and _has_terms(title, MARKET_TERMS):
        score += 8
    if spec.key == "eu_pork" and _has_terms(lead, ("Germany", "German", "Deutschland", "독일")):
        score += 8
    if (spec.key in MARKET_CONTEXT_SECTIONS and not article.get('searchResult')
            and not article.get('headlineOnly') and source._explanatory_market_excerpt(spec.key, str(article.get('body', '')))):
        # Verified causal market reporting outranks a repetitive statistical
        # release; ease of deterministic summarization is not editorial value.
        score += 24
    return score


def _parse_date(value: str) -> date | None:
    value = unicodedata.normalize("NFKC", value).strip()
    for pattern, order in ((r"(20\d{2})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})", (1, 2, 3)),
                           (r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", (3, 2, 1))):
        match = re.search(pattern, value)
        if match:
            try:
                return date(*(int(match.group(index)) for index in order))
            except ValueError:
                return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, OverflowError):
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.replace("Sept ", "Sep "), fmt).date()
        except ValueError:
            pass
    return None


def _publication_date(value: str, spec: SectionSpec) -> date | None:
    # Japanese/Korean publishers often encode publication in UTC. A 15:00Z
    # timestamp belongs to the NEXT local day, not an out-of-week old article.
    if spec.language in ('ja', 'ko'):
        try:
            stamp = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            if stamp.tzinfo is not None:
                return stamp.astimezone(timezone(timedelta(hours=9))).date()
        except (ValueError, TypeError):
            pass
    return _parse_date(value)


def _json_nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_nodes(child)


def _original_article(candidate: dict[str, Any], spec: SectionSpec) -> dict[str, Any] | None:
    """Use the publisher, then its explicit public NAVER syndicated article.

    NAVER's API returns both originallink and link. A publisher's JS-only page
    is not an access grant to a private API; its already-public syndicated copy
    can instead provide the original dated reporting, never the search snippet.
    """
    article = _read_original_article(candidate, spec)
    if article:
        return article
    public_url = str(candidate.get("publicNewsUrl", ""))
    if public_url != candidate.get("url") and urlparse(public_url).hostname in (
        "n.news.naver.com", "news.naver.com", "m.news.naver.com"
    ):
        article = _read_original_article({**candidate, "url": public_url}, spec)
        if article:
            article["originalUrl"] = str(candidate.get("url", ""))
            article["publisher"] = str(candidate.get("publisher") or article["publisher"])
            return article
    return None


def _read_original_article(candidate: dict[str, Any], spec: SectionSpec) -> dict[str, Any] | None:
    """Read title/date/body, without sidebars, unrelated headlines or snippets."""
    url = str(candidate.get("url", ""))
    if urlparse(url).scheme not in ("https", "http"):
        return None
    if urlparse(url).path.lower().endswith(".pdf"):
        return _pdf_article(candidate, spec)
    try:
        soup = source._download_soup(url)
    except source.ArticleDigestError:
        return None
    # RSS links can lead to the Google interstitial, not an original article.
    # Never summarize that wrapper as if it were publisher evidence.
    if urlparse(url).hostname == "news.google.com":
        canonical = soup.select_one("link[rel='canonical'][href]")
        original_url = str(canonical.get("href", "")) if canonical else ""
        if urlparse(original_url).hostname in (None, "news.google.com"):
            return None
        return _original_article({**candidate, "url": original_url}, spec)
    title_tag = soup.select_one('#main-title, [itemprop="headline"], h1.entry-title')
    title = source._clean_text(str(title_tag.get("content") or title_tag.get_text(" ", strip=True))) if title_tag else source._meta_value(soup, "property", "og:title")
    if not title:
        title_tag = next((heading for heading in soup.select("h1") if heading.get_text(' ', strip=True)), None)
        title = source._clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
    if title in ("댓글", "로그인", "뉴스", "Comments", "News"):
        title = str(candidate.get("title", ""))
    title = title or str(candidate.get("title", ""))
    published = None
    for attr, name in (("property", "article:published_time"), ("name", "pubdate"), ("name", "date")):
        published = _publication_date(source._meta_value(soup, attr, name), spec)
        if published:
            break
    schema_body = ""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            nodes = _json_nodes(json.loads(script.get_text()))
            for node in nodes:
                types = node.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if any(item in types for item in ("NewsArticle", "Article", "BlogPosting", "WebPage")):
                    published = published or _publication_date(str(node.get("datePublished", "")), spec)
                    schema_body = schema_body or source._clean_text(str(node.get("articleBody", "")))
        except (ValueError, TypeError):
            continue
    if not published:
        element = soup.select_one("time, .release-date, .release-date-label, .news-detail__author .date, .entry-date")
        if element:
            published = _publication_date(str(element.get("datetime", "")) or element.get_text(" ", strip=True), spec)
    # A listing/API publication date is evidence; the report date is NOT.
    published = published or candidate.get("publishedDate")
    # CSS selector unions return document order, not specificity. Prefer the
    # actual article text over an earlier wrapper containing menus/sidebars.
    body_element = next((element for selector in (
        ".articleView .viewer article", "#article_conent",
        "#news-contents", "#newsBody", "#dic_area", "#newsct_article", "#article-view-content-div", "[itemprop='articleBody']",
        ".elementor-widget-theme-post-content",
        ".tdb_single_content", ".td-post-content", ".post_page", ".content-main.cms-article", ".story-news.article",
        ".news-detail__content", "#articletxt", "#articleBody", "#article_content", "#divNews",
        "#r7-article-content", ".article_body", ".article-body", ".article__body", ".article_txt", ".article-text",
        ".news_body", ".entry-content", ".article-content", ".news-content", ".content-detail",
        ".post-content", ".entry-body", ".articleBody", ".texto", ".article_view"
    ) if (element := soup.select_one(selector)) is not None), None) or soup.find("article")
    body = schema_body
    if body_element:
        if body_element.get("id") == "newsBody":
            for widget in body_element.select(".headline, .favoriteAD, .iniframe, #realTalkWrap"):
                widget.decompose()
        for generated in body_element.select("details"):
            if "Produzido pela Ri7a" in generated.get_text(' ', strip=True):
                generated.decompose()  # publisher AI output is not original evidence
        for unwanted in body_element.select("script, style, nav, aside, footer, form, iframe, figure, figcaption, .caption, .photoCaption, .img_desc, [class*='related'], [class*='Related'], .advertisement, .ad, .sharedaddy, .page_title, .post_title, .post_info, .comment-respond, .ai-summary, #aiSummary, .keyword_wrap, .tag-list, .article-tags, .b-article-body-link-list__container"):
            unwanted.decompose()
        body = source._clean_text(body_element.get_text(" ", strip=True))
        body = re.split(r"\bRelated Articles\b|\bYou May Also Like\b|関連記事|関連ニュース|◎공감언론|Copyright\s*©|관련기사\s", body, maxsplit=1, flags=re.I)[0].strip()
    if len(body) < 100:
        # Older publisher themes often have no semantic article selector.
        # Use substantial paragraphs in main only, not the whole page/menu.
        main = soup.find("main")
        if main:
            paragraphs = [source._clean_text(p.get_text(" ", strip=True)) for p in main.select("p")
                          if not p.find_parent(["nav", "aside", "footer", "form"])]
            body = " ".join(p for p in paragraphs if len(p) >= 40)
    if len(body) < 100 or not isinstance(published, date):
        return None
    lang_tag = soup.find("html")
    language = str(lang_tag.get("lang", spec.language)).split("-", 1)[0].lower() if lang_tag else spec.language
    # CMS lang="en" is sometimes only a theme default. Verify actual scripts
    # before rejecting Japanese/Korean text, without accepting Chinese prose.
    if language in ("", "en", spec.language) and spec.language == "ko" and len(re.findall(r"[가-힣]", body)) >= 50:
        language = "ko"
    elif language in ("", "en", spec.language) and spec.language == "ja" and len(re.findall(r"[\u3040-\u30ff]", body)) >= 30:
        language = "ja"
    if language and language != spec.language:
        return None
    if spec.domestic and len(re.findall(r"[가-힣]", body)) < 30:
        return None
    canonical = soup.select_one("link[rel='canonical'][href]")
    canonical_url = urljoin(url, str(canonical.get("href"))) if canonical else url
    if urlparse(canonical_url).hostname != urlparse(url).hostname:
        canonical_url = url
    article = {"title": title, "url": canonical_url, "publishedDate": published,
            "publisher": source._meta_value(soup, "property", "og:site_name") or str(candidate.get("publisher") or spec.publisher),
            "body": body[:7000], "briefBody": body[:2400], "sourceLanguage": language or spec.language,
            "headlineOnly": False, "searchResult": False}
    article["briefBody"] = _editorial_excerpt(article["body"], title, spec)
    return article


def _species_excerpt(body: str, spec: SectionSpec) -> str:
    """Keep original target-species sentences, not a different meat or stocks.

    Original body remains intact for relevance/date checks. This is extraction,
    not a translation or invention, and numeric context stays in each sentence.
    """
    sentences = re.split(r"(?<=[.!?。])\s+|(?<=。)", body)
    selected = []
    for index, sentence in enumerate(sentences):
        if not _has_terms(sentence, SPECIES_TERMS[spec.species]) or not _has_terms(sentence, MARKET_TERMS):
            continue
        if index and re.match(r"또\s|또한\s|이어\s|이들\s|These\s|This\s|Meanwhile\s|In addition\s|同協会|同社", sentence.strip(), re.I):
            predecessor = sentences[index - 1].strip()
            if len(predecessor) <= 500 and (not selected or selected[-1] != predecessor):
                selected.append(predecessor)
        selected.append(sentence.strip())
    # Don't feed only a dangling pronoun/cross-reference without its context.
    substantive = [sentence for sentence in selected if len(sentence) >= 20]
    excerpt = " ".join(substantive)
    if not substantive:
        return body[:2400]
    # Stop only at a complete original sentence, never slice midway through
    # the last statistic or its increase/decrease direction.
    kept = []
    for sentence in substantive:
        if len(" ".join(kept + [sentence])) > 2400:
            break
        kept.append(sentence)
    return " ".join(kept) if kept else substantive[0]


def _editorial_excerpt(body: str, title: str, spec: SectionSpec) -> str:
    """Focus a headline-aligned issue, not the article's largest numeric list.

    Keep one intact original passage and its pronoun context. The full body is
    retained for date/country/relevance checks; this changes only model input.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|(?<=。)", body) if len(s.strip()) >= 20]
    anchors = [i for i, s in enumerate(sentences) if _has_terms(s, SPECIES_TERMS[spec.species]) and _has_terms(s, MARKET_TERMS)]
    # A metric may retain its product only in the preceding sentence (e.g.
    # '브라질산 계란의 수입 단가. 개당 수입 가격은 ...'). Keep that
    # explicit subject binding instead of preferring a later political quote.
    for i, sentence in enumerate(sentences):
        if (i and i not in anchors and _has_terms(sentences[i - 1], SPECIES_TERMS[spec.species])
                and re.search(r"개당|kg당|파운드당|per\s+(?:egg|kg|pound)", sentence, re.I)
                and re.search(r"\d[\d,.]*\s*(?:원|엔|달러|%|euros?\b|dollars?\b)", sentence, re.I)):
            anchors.append(i)
    if not anchors:
        return _species_excerpt(body, spec)
    title_themes = [terms for terms in EDITORIAL_TOPICS.values() if _has_terms(title, terms)]
    countries = tuple(dict.fromkeys(term for term in FOREIGN_TERMS + spec.regions
                                   if len(term) > 1 and (term in title or (not spec.domestic and term in spec.regions))))
    if spec.key == 'eu_pork' and _has_terms(title, ('EU', 'European Union')):
        countries = tuple(dict.fromkeys(countries + ('European Union', 'EU', '유럽연합')))
    periods = tuple(term for term in ('first half', 'second half', '상반기', '하반기', '上半期', '下半期') if term in title)
    headline_actions = tuple(term for term in ('검역', '재개', '중단', '관세', '가격', '수입 단가', '회수', '리콜') if term in title)
    headline_words = tuple(dict.fromkeys(word for word in re.findall(r"[A-Za-z]{4,}", title)
                                        if word.casefold() not in {'with', 'from', 'that', 'this', 'into', 'more', 'news'}))
    other_species = tuple(term for species, terms in SPECIES_TERMS.items() if species != spec.species
                          for term in terms if term not in SPECIES_TERMS[spec.species])
    def score(sentence):
        market_change = bool(re.search(
            r"공급\s*(?:압력|부족|증가|감소)|수요\s*(?:약화|증가|감소)|가격.{0,30}(?:상승|하락|비교|대비)|"
            r"수입\s*(?:가격|단가)|생산량|도축두수|출하량|수입량|수출량|시장\s*접근|"
            r"supply pressures|weaker (?:international )?demand|demand (?:is |has )?(?:weak|strong|moderate)|"
            r"prices?.{0,35}(?:higher|lower|rose|fell|remain firm|steady)|production (?:days|volume)|export volume", sentence, re.I))
        measurement = bool(re.search(r"\d[\d,.]*\s*(?:원|엔|달러|%|톤|두|마리|pounds?\b|tonnes?\b|euros?\b)", sentence, re.I))
        incidental = bool(re.search(r"정치적\s*(?:의혹|논란)|개인적\s*친분|좌파|커넥션|"
            r"anniversary|conference|event brought together|opening remarks|행사\s*소개", sentence, re.I))
        return (sum(_has_terms(sentence, terms) > 0 for terms in title_themes) * 8
                + _has_terms(sentence, countries) * 9
                + _has_terms(sentence, periods) * 10
                + _has_terms(sentence, headline_actions) * 12
                + _has_terms(sentence, headline_words) * 3
                + _has_terms(sentence, ("때문", "따른", "영향", "관세", "검역", "재개", "due to", "because", "owing to")) * 4
                + _has_terms(sentence, SPECIES_TERMS[spec.species]) * 3
                + _has_terms(sentence, ('시장가격', '소매가격', '도매가격', '평균가격', '가격은', '가격이', '가격 상승', '가격 하락', '북한 돈')) * 8
                + market_change * 22 + measurement * 12
                - incidental * 25
                - (20 if not spec.domestic and _has_terms(sentence, other_species) else 0)
                - (20 if re.search(r"20\d{2}년.*(?:무역통계|기록|수출액)|통계에 따르면", sentence)
                   and not any(year in title for year in re.findall(r"20\d{2}", sentence)) else 0))
    anchor = max(anchors, key=lambda i: (score(sentences[i]), -i))
    selected = [sentences[anchor]]
    if anchor and (not _has_terms(selected[0], SPECIES_TERMS[spec.species])
                   or re.match(r"이는|이를|이처럼|이에|여기에|또\s|또한\s|These\s|This\s|They\s|同社|同協会", selected[0], re.I)):
        selected.insert(0, sentences[anchor - 1])
    # Foreign market wraps often explain the headline statistic immediately
    # after it. Preserve nearby context instead of translating a naked figure.
    if not spec.domestic:
        for sentence in sentences[anchor + 1:anchor + 4]:
            if _has_terms(sentence, other_species) and not _has_terms(sentence, SPECIES_TERMS[spec.species]):
                break  # the next species' market is not the cause of this one
            selected.append(sentence)
        for sentence in sentences:
            if sentence not in selected and re.search(r"primeiro passo|Ainda faltam.*etapas", sentence, re.I):
                selected.append(sentence)
    return " ".join(selected)


@cancellation_checkpoint
@ttl_cache(seconds=300, maxsize=16)
def _public_pdf_text(url: str) -> str:
    parts = urlparse(url)
    encoded_url = urlunparse(parts._replace(path=quote(parts.path, safe="/%")))
    request = Request(encoded_url, headers={"User-Agent": source.PUBLIC_USER_AGENT, "Accept": "application/pdf"})
    try:
        with cancellable_lock(source._HTTP_SLOTS):
            with urlopen(request, timeout=source.REQUEST_TIMEOUT_SECONDS) as response:
                data = response.read()
        check_article_cancelled()
        with source.pymupdf.open(stream=data, filetype="pdf") as document:
            return source._clean_text(" ".join(page.get_text("text", sort=True) for page in document))[:7000]
    except ArticleDraftCancelled:
        raise
    except Exception as error:
        raise source.ArticleDigestError("공개 PDF 기사 원문을 읽지 못했습니다.") from error


def _pdf_article(candidate: dict[str, Any], spec: SectionSpec) -> dict[str, Any] | None:
    published = candidate.get("publishedDate")
    if not isinstance(published, date):
        return None
    try:
        body = _public_pdf_text(str(candidate["url"]))
    except source.ArticleDigestError:
        return None
    if len(body) < 100:
        return None
    # PDF listings have no html language tag. Check actual scripts, not just
    # the source label, before treating them as native-language evidence.
    script = r"[\u3040-\u30ff]" if spec.language == "ja" else r"[가-힣]" if spec.language == "ko" else r"[A-Za-z]"
    if len(re.findall(script, body)) < 20:
        return None
    return {**candidate, "body": body, "briefBody": body[:2400], "sourceLanguage": spec.language,
            "headlineOnly": False, "searchResult": False}


def _usda_pdf_article(url: str, title: str, start: date, end: date,
                      *, expected_date: date | None = None) -> dict[str, Any] | None:
    """Check the actual PDF header/report dates, including archive listings."""
    body = _public_pdf_text(url)
    # USDA dates are month/day/year; publication and reporting dates must agree.
    header = re.search(r"\b([A-Za-z]{3}\s+\d{1,2},\s+20\d{2})\b", body[:500])
    published = _parse_date(header.group(1)) if header else None
    report = re.search(r"\bReport(?:ed)? for:?\s*(\d{1,2})/(\d{1,2})/(20\d{2})", body[:600], re.I)
    if report:
        try:
            reported = date(int(report[3]), int(report[1]), int(report[2]))
        except ValueError:
            return None
    else:
        report = re.search(r"\bReported for\s+([A-Za-z]{3}\s+\d{1,2},\s+20\d{2})", body[:600], re.I)
        reported = _parse_date(report[1]) if report else None
    if (not published or published != reported or not start <= published <= end
            or (expected_date is not None and published != expected_date)
            or title not in body[:300]):
        return None
    lead = re.split(r"NEGOTIATED REGIONAL VOLUME MOVEMENT|Source:\s*USDA", body, maxsplit=1)[0]
    lead = re.sub(r"^.*?Report(?:ed)? for:?\s*(?:\d{1,2}/\d{1,2}/20\d{2}|[A-Za-z]{3}\s+\d{1,2},\s+20\d{2})\s*", "", lead, count=1)
    return {"title": title, "url": url, "publishedDate": published, "publisher": "USDA AMS",
            "body": body, "briefBody": lead, "sourceLanguage": "en", "sourceCountry": "US",
            "headlineOnly": False, "searchResult": False}


@cancellation_checkpoint
@ttl_cache(seconds=300, maxsize=64)
def _usda_archive_page(url: str) -> str | None:
    """One bounded public GET; an unavailable archive must not add long retries."""
    request = Request(url, headers={"User-Agent": source.PUBLIC_USER_AGENT, "Accept": "text/html"})
    try:
        with cancellable_lock(source._HTTP_SLOTS):
            with urlopen(request, timeout=USDA_ARCHIVE_TIMEOUT_SECONDS) as response:
                raw = response.read()
                charset = response.headers.get_content_charset()
        return source._decode_source_html(raw, charset)
    except OSError:
        return None


def _usda_archive_article(spec: SectionSpec, start: date, end: date) -> dict[str, Any] | None:
    """Use the visible USDA archive GET form and dated PDF links for this week.

    Report Date is an exact-date filter, not a range. Search this week's latest
    weekday first and stop immediately if the public archive is unavailable.
    A listing date alone cannot authorize assigning that date to a PDF.
    """
    if spec.key not in USDA_DAILY_REPORTS:
        return None
    latest_url, title = USDA_DAILY_REPORTS[spec.key]
    slug = re.search(r"ams_(\d+)\.pdf$", latest_url)[1]
    requested = end
    while requested >= start:
        if requested.weekday() >= 5:
            requested -= timedelta(days=1)
            continue
        url = USDA_PUBLIC_ARCHIVE_URL + "?" + urlencode({
            "field_slug_id_value": slug, "field_report_date_end_value": requested.isoformat(),
        })
        html = _usda_archive_page(url)
        if html is None:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select("#filerepo-reports-table tbody tr"):
            cells = row.select("td")
            if len(cells) < 7 or cells[0].get_text(strip=True) != slug:
                continue
            report_date = _parse_date(cells[4].get_text(" ", strip=True))
            stamp = re.match(r"(\d{2})-(\d{2})-(20\d{2})\b", cells[3].get_text(" ", strip=True))
            try:
                published = date(int(stamp[3]), int(stamp[1]), int(stamp[2])) if stamp else None
            except ValueError:
                continue
            if report_date != requested or not published or not start <= published <= end:
                continue
            for link in cells[6].select('a[href]'):
                pdf_url = urljoin(url, str(link["href"]))
                parts = urlparse(pdf_url)
                if (parts.scheme != "https" or parts.hostname != urlparse(USDA_PUBLIC_ARCHIVE_URL).hostname
                        or not parts.path.startswith(f"/filerepo/sites/default/files/{slug}/")
                        or not parts.path.lower().endswith(".pdf")):
                    continue
                try:
                    article = _usda_pdf_article(pdf_url, title, start, end, expected_date=report_date)
                except source.ArticleDigestError:
                    continue
                if article:
                    return article
        requested -= timedelta(days=1)
    return None


def _japanese_egg_market_article(start: date, end: date) -> dict[str, Any] | None:
    """Read the public JA daily quotation, with its own announcement date.

    The news page can have no new editorial story while JA still publishes a
    dated local market report. A table cell is tied to its market, M size,
    benchmark column and unit; no current row is relabelled as a historical week.
    """
    soup = source._download_soup(JAPANESE_EGG_MARKET_URL)
    announcement = soup.select_one(".publication-date")
    tokyo = soup.select_one("#tokyo")
    if announcement is None or tokyo is None:
        return None
    stamp = source._clean_text(announcement.get_text(" ", strip=True))
    published = _parse_date(stamp) if "発表" in stamp else None
    if published is None or not start <= published <= end:
        return None
    table = tokyo.find("table")
    unit = tokyo.select_one(".unit")
    if table is None or unit is None or not re.search(r"円\s*/\s*kg", unit.get_text(" ", strip=True), re.I):
        return None
    headers = [cell.get_text(" ", strip=True) for cell in table.select("thead th")]
    if [re.sub(r"\s+", "", value) for value in headers] != ["東京", "高値", "基準値", "安値"]:
        return None
    rows = {row.find("th").get_text(" ", strip=True): [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            for row in table.select("tbody tr") if row.find("th") is not None}
    size = rows.get("M", [])
    market = rows.get("市況", [])
    arrivals = rows.get("入荷量", [])
    if (len(size) != 4 or not re.fullmatch(r"\d+(?:\.\d+)?", size[1])
            or len(market) != 1 or len(arrivals) != 1):
        return None
    title = "JA全農たまご 鶏卵相場（東京）"
    # Keep the exact published Japanese table as evidence, rather than a
    # translated sentence whose values a summarizer could treat as source text.
    body = "\n".join((title, stamp, table.get_text(" ", strip=True), unit.get_text(" ", strip=True)))
    return {"title": title, "url": JAPANESE_EGG_MARKET_URL, "publishedDate": published,
            "publisher": "JA全農たまご", "body": body, "briefBody": body,
            "sourceLanguage": "ja", "sourceCountry": "JP", "sourceMethod": "official",
            "headlineOnly": False, "searchResult": False}


def _official_market_article(spec: SectionSpec, start: date, end: date) -> dict[str, Any] | None:
    """Public market releases whose latest URL is dated inside the document.

    A current URL is not a publication date. Never label a stale report with
    the requested week, and never borrow a linked previous-week PDF's date.
    """
    if spec.key == "japan_egg":
        article = _japanese_egg_market_article(start, end)
        if not article:
            return None
    elif spec.key == "eu_pork":
        soup = source._download_soup(GERMAN_PORK_REPORT_URL)
        stamp = soup.select_one('time[itemprop="datePublished"][datetime]')
        heading = soup.select_one('h1[itemprop="headline"]')
        lead = soup.select_one('main h5[itemprop="description"]')
        if not stamp or not heading or not lead:
            return None
        published = _parse_date(str(stamp.get("datetime", "")))
        body = source._clean_text(lead.get_text(" ", strip=True))
        title = source._clean_text(heading.get_text(" ", strip=True))
        if not published or not start <= published <= end or len(body) < 100:
            return None
        article = {"title": title, "url": GERMAN_PORK_REPORT_URL, "publishedDate": published,
                   "publisher": "Landwirtschaftskammer Rheinland-Pfalz", "body": body,
                   "briefBody": body, "sourceLanguage": "de", "sourceCountry": "DE",
                   "headlineOnly": False, "searchResult": False}
    elif spec.key in USDA_DAILY_REPORTS:
        url, title = USDA_DAILY_REPORTS[spec.key]
        try:
            article = _usda_pdf_article(url, title, start, end)
        except source.ArticleDigestError:
            article = None
        if not article:
            article = _usda_archive_article(spec, start, end)
        if not article:
            return None
    else:
        return None
    return {**article, "sourceMethod": "official"} if _relevance(article, spec, trusted_country=True) >= 0 else None


def _same_publisher_host(first: str, second: str) -> bool:
    """Allow the publisher's conventional www alias, never other domains."""
    left = (urlparse(first).hostname or "").lower().removeprefix("www.")
    right = (urlparse(second).hostname or "").lower().removeprefix("www.")
    return bool(left) and left == right


def _feed_candidates(xml: str, url: str, spec: SectionSpec, start: date, end: date) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    results = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        fields = {child.tag.split("}")[-1].lower(): child for child in item}
        text = lambda key: "".join(fields[key].itertext()).strip() if key in fields else ""
        published = _parse_date(text("pubdate") or text("published"))
        link = fields.get("link")
        href = ((link.get("href") or (link.text or "")) if link is not None else "").strip()
        if not published or not start <= published <= end or not href:
            continue
        item_url = urljoin(url, href)
        if not _same_publisher_host(item_url, url):
            continue
        item = {"title": source._clean_text(text("title")), "url": item_url,
                "publishedDate": published, "publisher": spec.publisher,
                "body": source._clean_text(BeautifulSoup(text("description") or text("summary"), "html.parser").get_text(" ", strip=True))}
        results.append(item)
    return results


def _listing_candidates(soup: BeautifulSoup, url: str, spec: SectionSpec, start: date, end: date) -> list[dict[str, Any]]:
    results = []
    anchors = soup.select("h2 a[href], h3 a[href], .td-module-title a[href], .release-item a.release-txt[href], a.item-news__link[href], a.post_link_wrapper[href]")
    if _same_publisher_host(url, "https://www.beefcentral.com/"):
        anchors.extend(anchor for heading in soup.select("h4")
                       if (anchor := heading.find_parent("a", href=True)) is not None)
    if urlparse(url).hostname == "www.jz-tamago.co.jp":
        anchors.extend(a for a in soup.select("li a[href]") if a.select_one(".date") is not None)
    for anchor in anchors:
        title_element = anchor.select_one(".title, .post_loop_title, h4") or anchor
        title = source._clean_text(title_element.get_text(" ", strip=True))
        href = urljoin(url, str(anchor.get("href", "")))
        if len(title) < 8 or not _same_publisher_host(href, url):
            continue
        card = anchor if "post_link_wrapper" in anchor.get("class", []) else anchor.find_parent(class_="release-item") or anchor.find_parent("article") or anchor.find_parent("li") or anchor.find_parent(class_=re.compile(r"td_module|item-news|news-item|post-item|item-details")) or anchor.parent.parent
        published = None
        if card:
            stamp = card.select_one("time, .release-date, .date, .entry-date, .post_loop_date")
            if stamp:
                published = _parse_date(str(stamp.get("datetime", "")) or stamp.get_text(" ", strip=True))
        if published and not start <= published <= end:
            continue
        excerpt = card.select_one(".td-excerpt, .excerpt, .post_loop_excerpt") if card else None
        results.append({"title": title, "url": href, "publishedDate": published,
                        "publisher": spec.publisher, "body": source._clean_text(excerpt.get_text(' ', strip=True)) if excerpt else title})
    return results


def _choose_original(candidates: list[dict[str, Any]], spec: SectionSpec, start: date, end: date,
                     *, trusted_country: bool = False, exclude_urls: frozenset[str] = frozenset(),
                     attempted_urls: set[str] | None = None, diagnostics: dict[str, int] | None = None) -> dict[str, Any] | None:
    seen = set()
    ranked = []
    for candidate in candidates:
        url = candidate.get("url")
        if not url or url in seen or url in exclude_urls or (attempted_urls is not None and url in attempted_urls):
            continue
        seen.add(url)
        if urlparse(str(url)).hostname == "news.google.com":
            # Opaque RSS redirect pages have neither original text nor a
            # publisher URL in their canonical tag. Resolve headlines in the
            # public-search stage instead of downloading every wrapper here.
            if diagnostics is not None and (attempted_urls is None or url not in attempted_urls):
                diagnostics["redirectsUnresolved"] = diagnostics.get("redirectsUnresolved", 0) + 1
            if attempted_urls is not None:
                attempted_urls.add(url)
            continue
        published = candidate.get("publishedDate")
        if published is not None and not start <= published <= end:
            continue
        # Listings have no body yet; only species/event screening is possible.
        headline = str(candidate.get("title", ""))
        discovery_text = headline + ' ' + str(candidate.get("body", ""))
        if not _has_terms(discovery_text, SPECIES_TERMS[spec.species]):
            continue
        if _has_terms(str(candidate.get("title", "")), NON_MARKET_TERMS):
            continue
        ranked.append(candidate)
    ranked.sort(key=lambda a: (_relevance(a, spec, trusted_country=trusted_country), a.get("publishedDate") or date.min), reverse=True)
    verified = []
    # Hard bound on upstream requests. A bad source never causes an unbounded crawl.
    # Check the next tier only if the first ten fail. Requests remain bounded,
    # but one inaccessible/irrelevant top result cannot hide a relevant 11th.
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="market-original") as executor:
        for tier in (ranked[:10], ranked[10:18]):
            if verified:
                break
            for offset in range(0, len(tier), 3):
                batch = tier[offset:offset + 3]
                if attempted_urls is not None:
                    attempted_urls.update(candidate["url"] for candidate in batch)
                if diagnostics is not None:
                    diagnostics["originalsChecked"] = diagnostics.get("originalsChecked", 0) + len(batch)
                # map_article_tasks preserves ranking order and cancellation
                # context while three independent publisher requests overlap.
                for article in map_article_tasks(executor, lambda candidate: _original_article(candidate, spec), batch):
                    if not article:
                        if diagnostics is not None:
                            diagnostics["unreadable"] = diagnostics.get("unreadable", 0) + 1
                        continue
                    if not start <= article["publishedDate"] <= end:
                        if diagnostics is not None:
                            diagnostics["outsideWeek"] = diagnostics.get("outsideWeek", 0) + 1
                        continue
                    if article["url"] in exclude_urls:
                        continue
                    score = _relevance(article, spec, trusted_country=trusted_country)
                    if score >= 0 and article["url"] not in {item["url"] for item in verified}:
                        article["score"] = score
                        verified.append(article)
                    elif score < 0 and diagnostics is not None:
                        diagnostics["irrelevant"] = diagnostics.get("irrelevant", 0) + 1
                if len(verified) >= 3:
                    break
    if not verified:
        return None
    verified.sort(key=lambda a: (a["score"], a["publishedDate"]), reverse=True)
    return {**verified[0], "alternatives": verified[1:3]}


def _candidate_links(article: dict[str, Any], spec: SectionSpec, start: date, end: date,
                     *, search_missing: bool = True) -> list[dict[str, str]]:
    links, originals, searched = read_candidate_links(article, spec, start, end, search_missing=search_missing)
    # The collector owns this mutable candidate. Keep the downloaded evidence
    # available to summary recovery without exposing it in public metadata.
    article["_candidateLinkOriginals"] = originals
    article["_candidateLinksSearched"] = bool(article.get("_candidateLinksSearched") or searched)
    return links


def read_candidate_links(article: dict[str, Any], spec: SectionSpec, start: date, end: date,
                         *, search_missing: bool = True) -> tuple[list[dict[str, str]], list[dict[str, Any]], bool]:
    """Two verified same-week originals, without extra LLM inference or snippets."""
    selected = str(article.get("url", ""))
    seen = {selected, str(article.get("originalUrl", selected))}
    links = []
    originals = []
    searched = False

    def add(items):
        for candidate in items:
            url = str(candidate.get("originalUrl") or candidate.get("url", ""))
            published = candidate.get("publishedDate")
            if (url in seen or urlparse(url).scheme not in ("http", "https")
                    or not isinstance(published, date) or not start <= published <= end
                    or _relevance(candidate, spec, trusted_country=True) < 0):
                continue
            seen.add(url)
            title = re.sub(r"\s+", " ", str(candidate.get("title", ""))).strip()
            if not title:
                continue
            links.append({"url": url, "title": title if len(title) <= 72 else title[:71] + "…",
                          "publisher": str(candidate.get("publisher", "")),
                          "publishedDate": published.isoformat()})
            originals.append(candidate)
            if len(links) == 2:
                return

    add(article.get("alternatives", []) + article.get("_candidateLinkOriginals", []))
    if len(links) < 2 and search_missing and not article.get("_candidateLinksSearched", False):
        searched = True
        try:
            other = _search_article(spec, start, end, exclude_urls=frozenset(seen))
            if other:
                add([other] + other.get("alternatives", []))
        except ArticleDraftCancelled:
            raise
        except Exception:
            # Optional links must not prevent the main draft from completing.
            pass
    return links[:2], originals[:2], searched


def _abpa_chicken_article(spec: SectionSpec, start: date, end: date) -> dict[str, Any] | None:
    """Discover public ABPA news, then require the publisher's original date/body."""
    if spec.key != "brazil_chicken":
        return None
    try:
        xml = source._download_html(ABPA_CHICKEN_NEWS_FEED_URL)
    except source.ArticleDigestError:
        return None
    candidates = _feed_candidates(xml, ABPA_CHICKEN_NEWS_FEED_URL, spec, start, end)
    # An RSS timestamp is only discovery evidence here. Requiring an original
    # publication stamp prevents a refreshed feed entry from relabeling old news.
    candidates = [{key: value for key, value in candidate.items() if key != "publishedDate"}
                  for candidate in candidates]
    chosen = _choose_original(candidates, spec, start, end)
    if not chosen:
        return None
    originals = [chosen] + chosen.get("alternatives", [])
    originals = [item for item in originals if _has_terms(str(item.get("body", "")), SPECIES_TERMS[spec.species])
                 and _has_terms(str(item.get("body", "")), MARKET_TERMS)]
    return {**originals[0], "alternatives": originals[1:3], "sourceMethod": "official"} if originals else None


def _preferred_site_article(spec: SectionSpec, start: date, end: date) -> dict[str, Any] | None:
    candidates = []
    seen_feeds = set()
    reachable = 0
    pending = list(spec.listings)
    seen_pages = set()
    attempted_originals: set[str] = set()
    added_search = False
    while pending and len(seen_pages) < len(spec.listings) + 5:
        url = pending.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            soup = source._download_soup(url)
        except source.ArticleDigestError:
            continue
        reachable += 1
        candidates.extend(_listing_candidates(soup, url, spec, start, end))
        # Search only a public GET form discovered on the publisher's page.
        # Specific market terminology finds articles not in the latest feed.
        term = {"eu_pork": "pig", "us_chicken": "broiler"}.get(spec.key)
        if term and not added_search:
            for form in soup.select("form"):
                action = urljoin(url, str(form.get("action") or url))
                if str(form.get("method", "get")).lower() == "get" and form.select_one('input[name="s"]') and _same_publisher_host(action, url):
                    pending.append(action.split("?", 1)[0] + "?" + urlencode({"s": term}))
                    added_search = True
                    break
        stamps = [_parse_date(str(t.get("datetime", "")) or t.get_text(' ', strip=True))
                  for t in soup.select("time, .cat-container .date, .post_loop_date")]
        stamps = [stamp for stamp in stamps if stamp]
        # Follow visible next-page links, stopping once dated listings reach
        # the beginning of the report week. Never guess AJAX/private endpoints.
        if not stamps or min(stamps) >= start:
            link = soup.select_one('a[rel="next"], a.next, .pagination a[aria-label="Next"], .page-nav a[aria-label="next-page"]')
            if link is None:
                link = next((a for a in soup.select('a[href]') if re.match(
                    r"^(?:Older Entries|Older Posts|Next)(?:\s|[»›→]|$)", a.get_text(' ', strip=True), re.I)), None)
            if link and link.get("href"):
                next_url = urljoin(url, str(link["href"]))
                if _same_publisher_host(next_url, url):
                    pending.append(next_url)
        # Follow only published RSS discovery links, not guessed/private APIs.
        page_feed_count = 0
        for link in soup.select('link[rel="alternate"][type="application/rss+xml"][href]'):
            feed_url = urljoin(url, str(link.get("href")))
            if feed_url in seen_feeds or "comments" in feed_url or not _same_publisher_host(feed_url, url):
                continue
            seen_feeds.add(feed_url)
            page_feed_count += 1
            try:
                candidates.extend(_feed_candidates(source._download_html(feed_url), feed_url, spec, start, end))
            except source.ArticleDigestError:
                pass
            if page_feed_count >= 2:
                break
        # Publish a verified preferred article as soon as its listing/feed is
        # sufficient. Older pagination is supplemental discovery, not a reason
        # to delay a ready primary draft. Failed originals are not redownloaded.
        if candidates:
            preferred = _choose_original(candidates, spec, start, end,
                                         trusted_country=spec.country in ("US", "BR", "JP"),
                                         attempted_urls=attempted_originals)
            if preferred:
                return preferred
    # US/BR/JP sites are local country sources; EuroMeatNews covers all countries
    # so Germany/EU evidence must occur in the actual article, not just the site.
    preferred = _choose_original(candidates, spec, start, end,
                                 trusted_country=spec.country in ("US", "BR", "JP"),
                                 attempted_urls=attempted_originals)
    if preferred:
        return preferred
    if spec.key == "brazil_chicken":
        abpa = _abpa_chicken_article(spec, start, end)
        if abpa:
            return abpa
    try:
        official = _official_market_article(spec, start, end)
    except source.ArticleDigestError:
        official = None
    if official:
        return official
    if spec.listings and not reachable:
        raise SourceUnavailable(f"{spec.publisher}의 공개 뉴스 목록에 연결하지 못했습니다.")
    return None


def _search_article(spec: SectionSpec, start: date, end: date, *, exclude_urls: frozenset[str] = frozenset(),
                    diagnostics: dict[str, int] | None = None) -> dict[str, Any] | None:
    candidates = []
    attempted_urls: set[str] = set()
    def choose(items, *, trusted_country=False):
        if diagnostics is not None:
            diagnostics["candidates"] = len({item.get("url") for item in items if item.get("url")})
        return _choose_original(items, spec, start, end, trusted_country=trusted_country,
                                exclude_urls=exclude_urls, attempted_urls=attempted_urls, diagnostics=diagnostics)
    def search(query):
        try:
            if spec.domestic:
                return source._search_naver_news(query, start, end)
            country = spec.country if spec.language != "en" else ("AU" if spec.country == "AU" else "US")
            return source._search_google_news_rss(query, start, end, language=spec.language,
                                                 country=country, edition=f"{country}:{spec.language}")
        except source.ArticleDigestError:
            return []
    # For Korean articles, compare country-specific AND broad topic searches
    # before choosing. A mediocre early hit must not hide a better global issue.
    initial_queries = (spec.queries + SEARCH_QUERIES[spec.key] if spec.domestic else
                       spec.queries + REFERENCE_SOURCE_QUERIES.get(spec.key, ())[:2])
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="market-search") as executor:
        for found in map_article_tasks(executor, search, initial_queries):
            candidates.extend(found)
    article = choose(candidates)
    if article:
        return article
    # Widen named-source coverage only after the unrestricted first search.
    # Two queries at most, parallel and using the same verified-original pool.
    reference_queries = cited_media_queries(spec.key, start) if spec.domestic else ()
    if reference_queries:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='market-reference-search') as executor:
            for found in map_article_tasks(executor, search, reference_queries):
                candidates.extend(found)
        article = choose(candidates)
        if article:
            return article
    # Different query phrasing, not just the same failed query repeatedly.
    extra = SEARCH_QUERIES[spec.key]
    if not spec.domestic:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-search-extra") as executor:
            for found in map_article_tasks(executor, search, extra):
                candidates.extend(found)
    article = choose(candidates)
    if article:
        return article
    # Bing publishes original publisher URLs in its public RSS redirect URL.
    # Read that documented-in-response link, without decoding opaque Google
    # tokens or calling private redirect endpoints. No cookies or API key.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-public-search") as executor:
        for found in map_article_tasks(executor, lambda query: _public_bing_candidates(query, spec, start, end), extra[:3]):
            candidates.extend(found)
    article = choose(candidates, trusted_country=spec.country == "JP")
    if article:
        return article
    originals = []
    for query in extra[:3]:
        originals.extend(_public_google_candidates(query, spec.language, start, end))
    # Match discovered RSS headlines to public publisher links. A wrapper is
    # never treated as article evidence, even when every other search fails.
    opaque = [item for item in candidates if urlparse(str(item.get("url", ""))).hostname == "news.google.com"
              and _has_terms(str(item.get("title", "")), SPECIES_TERMS[spec.species])
              and not _has_terms(str(item.get("title", "")), NON_MARKET_TERMS)]
    opaque.sort(key=lambda item: (_relevance(item, spec, trusted_country=spec.country in ("JP", "US", "BR")), item.get("publishedDate") or date.min), reverse=True)
    for item in opaque[:4]:
        host = urlparse(str(item.get("publisherUrl", ""))).hostname
        if host:
            matches = _public_google_candidates(f'site:{host} "{item["title"]}"', spec.language, start, end)
            # Search can return a different article from this publisher. Its
            # own publication metadata must establish the date; transferring
            # the RSS item's date can mislabel an old article as this week.
            originals.extend(match for match in matches
                             if urlparse(match["url"]).hostname == host)
    return choose(candidates + originals, trusted_country=spec.country == "JP")


def _public_bing_candidates(query: str, spec: SectionSpec, start: date, end: date) -> list[dict[str, Any]]:
    markets = {"pt": "pt-BR", "ja": "ja-JP", "ko": "ko-KR"}
    market = markets.get(spec.language, "en-AU" if spec.country == "AU" else "en-US")
    url = "https://www.bing.com/news/search?" + urlencode({"q": query, "format": "rss", "mkt": market, "count": 50})
    try:
        root = ET.fromstring(source._download_html(url))
    except (source.ArticleDigestError, ET.ParseError):
        return []
    results = []
    for item in root.findall(".//item"):
        published = _parse_date(item.findtext("pubDate", ""))
        if not published or not start <= published <= end:
            continue
        href = item.findtext("link", "").strip()
        parsed = urlparse(href)
        if parsed.hostname and (parsed.hostname == "bing.com" or parsed.hostname.endswith(".bing.com")):
            href = (parse_qs(parsed.query).get("url") or [""])[0]
        if urlparse(href).scheme not in ("http", "https"):
            continue
        results.append({"title": source._clean_text(item.findtext("title", "")), "url": href,
                        "publishedDate": published, "publisher": source._publisher_from_url(href),
                        "body": BeautifulSoup(item.findtext("description", ""), "html.parser").get_text(" ", strip=True),
                        "sourceLanguage": spec.language, "searchResult": True})
    return results


def _public_google_candidates(query: str, language: str, start: date, end: date) -> list[dict[str, Any]]:
    url = "https://www.google.com/search?" + urlencode({
        "q": query, "hl": language, "num": 10,
        "tbs": f"cdr:1,cd_min:{start:%m/%d/%Y},cd_max:{end:%m/%d/%Y}",
    })
    try:
        soup = source._download_soup(url)
    except source.ArticleDigestError:
        return []
    candidates = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href", ""))
        if href.startswith("/url?"):
            params = parse_qs(urlparse(href).query)
            href = (params.get("q") or params.get("url") or [""])[0]
        parsed = urlparse(href)
        host = parsed.hostname or ""
        if parsed.scheme not in ("https", "http") or not host or any(host == domain or host.endswith("." + domain) for domain in ("google.com", "google.co.jp", "google.com.br", "youtube.com", "gstatic.com")):
            continue
        heading = anchor.find("h3")
        title = source._clean_text(heading.get_text(" ", strip=True) if heading else anchor.get_text(" ", strip=True))
        if len(title) < 8:
            continue
        candidates.append({"title": title, "url": href, "body": title, "sourceLanguage": language,
                           "publisher": source._publisher_from_url(href)})
    return candidates


def _usmef_pair(start: date, end: date) -> dict[str, dict[str, Any]]:
    soup = source._download_soup(source.NEWSLINE_URL)
    entries = []
    for link in soup.select("a.board_content"):
        match = re.search(r"sampleOpenWin\('([^']+\.pdf)'", str(link.get("href", "")), re.I)
        if not match:
            continue
        url = urljoin(source.NEWSLINE_URL, match.group(1))
        stamp = re.search(r"/(20\d{2})(\d{2})(\d{2})/", url)
        if not stamp:
            continue
        try:
            published = date(*(int(part) for part in stamp.groups()))
        except ValueError:
            continue
        if start <= published <= end:
            entries.append((published, url))
    if not entries:
        return {}
    published, url = max(entries)
    texts = source._extract_usmef_market_texts(url)
    result = {}
    for key, species in (("us", "beef"), ("us_pork", "pork")):
        body = texts.get(species, "")
        if len(body) >= 120:
            result[key] = {"title": f"MEF NEWSLINE {published:%Y. %m. %d} · {'소고기' if species == 'beef' else '돼지고기'} 시장동향",
                           "publishedDate": published, "url": url, "publisher": "미국육류수출협회(USMEF) 뉴스라인",
                           "body": body, "briefBody": body, "sourceLanguage": "ko", "headlineOnly": False, "searchResult": False,
                           "sourceMethod": "preferred"}
    return result


def _find_section(spec: SectionSpec, start: date, end: date) -> dict[str, Any] | None:
    article = None
    preferred_error = None
    if spec.key == "australia":
        try:
            article = source._find_australia_beef_article(start, end)
        except source.ArticleDigestError as error:
            preferred_error = error
        if article and _relevance(article, spec) < 0:
            article = None
        if not article:
            # This Australian market publisher was discovered in public news
            # results. Read its advertised feeds/listings, not opaque wrappers.
            fallback_spec = replace(spec, publisher="Beef Central", listings=("https://www.beefcentral.com/",))
            try:
                article = _preferred_site_article(fallback_spec, start, end)
                if article:
                    article = {**article, "sourceMethod": "search"}
            except source.ArticleDigestError:
                pass
    elif spec.listings:
        try:
            article = _preferred_site_article(spec, start, end)
        except source.ArticleDigestError as error:
            preferred_error = error
    if article and start <= article["publishedDate"] <= end:
        return {**article, "sourceMethod": article.get("sourceMethod", "preferred")}
    diagnostics: dict[str, int] = {}
    article = _search_article(spec, start, end, diagnostics=diagnostics)
    if not article and preferred_error:
        raise SourceUnavailable(f"{spec.publisher} 원문 연결 실패 · {_search_failure_message(diagnostics)}") from preferred_error
    if not article and diagnostics:
        raise SourceUnavailable(_search_failure_message(diagnostics))
    return {**article, "sourceMethod": "naver" if spec.domestic else "search"} if article else None


def _search_failure_message(diagnostics: dict[str, int]) -> str:
    """Explain collection/selection failure without claiming no article exists."""
    checked = diagnostics.get("originalsChecked", 0)
    return (f"검색 후보 {diagnostics.get('candidates', 0)}건 · 원문 확인 {checked}건. "
            f"원문·언어 확인 불가 {diagnostics.get('unreadable', 0)}건, "
            f"검색 연결 미해결 {diagnostics.get('redirectsUnresolved', 0)}건, "
            f"기간 밖 {diagnostics.get('outsideWeek', 0)}건, 주제 불일치 {diagnostics.get('irrelevant', 0)}건. "
            "해당 주차의 적합한 공개 원문을 확보하지 못했습니다.")


def _broaden_editorial_candidate(article: dict[str, Any], spec: SectionSpec,
                                 start: date, end: date) -> dict[str, Any]:
    """Reuse the optional-link search early when a preferred item is too thin.

    At most one supplemental search, no model call or historical backfill. Its
    originals also supply the two optional links, avoiding another later crawl.
    A failed search must not discard an otherwise usable same-week primary.
    """
    if (spec.key not in MARKET_CONTEXT_SECTIONS or article.get('_candidateLinksSearched')
            or source._explanatory_market_excerpt(spec.key, str(article.get('body', '')))):
        return article
    native = source._native_report_sentence(spec.key, str(article.get('body', '')))
    if not native or not re.search(r'생산량?|입란수|입식수|출하두수|도축두수|사육두수|재고', native):
        return article
    primary_urls = frozenset(str(article.get(key, '')) for key in ('url', 'originalUrl') if article.get(key))
    try:
        other = _search_article(spec, start, end, exclude_urls=primary_urls)
    except ArticleDraftCancelled:
        raise
    except Exception:
        other = None
    candidates = [article] + list(article.get('alternatives', []))
    if other:
        candidates.extend([other] + other.get('alternatives', []))
    valid = []
    seen = set()
    for candidate in candidates:
        published = candidate.get('publishedDate')
        url = str(candidate.get('url', ''))
        original_url = str(candidate.get('originalUrl') or url)
        if (url in seen or not isinstance(published, date) or not start <= published <= end
                or candidate.get('headlineOnly') or candidate.get('searchResult')
                or urlparse(url).scheme not in ('http', 'https') or not urlparse(url).hostname
                or urlparse(original_url).scheme not in ('http', 'https') or not urlparse(original_url).hostname
                or len(str(candidate.get('body', ''))) < 100
                or _relevance(candidate, spec, trusted_country=spec.country in ('US', 'BR')) < 0):
            continue
        seen.add(url)
        valid.append(candidate)
    rich = [candidate for candidate in valid
            if source._explanatory_market_excerpt(spec.key, str(candidate['body']))]
    selected = max(rich, key=lambda candidate: _relevance(candidate, spec,
                   trusted_country=spec.country in ('US', 'BR'))) if rich else article
    return {**selected, 'alternatives': [candidate for candidate in valid if candidate['url'] != selected['url']][:4],
            '_candidateLinksSearched': True}


def _prefer_native_summary_candidate(article: dict[str, Any], spec: SectionSpec,
                                     start: date, end: date, allow_context: bool = True) -> dict[str, Any]:
    """Prefer a ready brief from existing verified same-section originals.

    No discovery or model call belongs here. Candidates still pass the full
    species/country gate; ease of summarizing cannot qualify a local retail
    promotion, a search snippet, or an article from another week. Country trust
    is retained only for countries already covered by preferred local sources.
    """
    candidates = [article] + article.get("alternatives", []) + article.get("_candidateLinkOriginals", [])
    seen = set()
    eligible = []
    for candidate in candidates:
        check_article_cancelled()
        published = candidate.get("publishedDate")
        url = str(candidate.get("url", ""))
        original_url = str(candidate.get("originalUrl") or url)
        body = str(candidate.get("body", ""))
        if url in seen or original_url in seen:
            continue
        seen.update((url, original_url))
        if (not isinstance(published, date) or not start <= published <= end
                or any(urlparse(value).scheme not in ("http", "https") or not urlparse(value).hostname
                       for value in (url, original_url))
                or candidate.get("searchResult") or candidate.get("headlineOnly") or len(body) < 100
                or (spec.domestic and (candidate.get("sourceLanguage", "ko") != "ko"
                                       or len(re.findall(r"[가-힣]", body)) < 30))
                or _relevance(candidate, spec, trusted_country=not spec.domestic and spec.country in ("US", "BR", "JP")) < 0):
            continue
        try:
            native = source._native_report_sentence(spec.key, body)
            fitted = source._fit_report_summary(native, spec.key, body) if native else None
            if fitted and not source._valid_brief(fitted, spec.key, body):
                fitted = None
            contextual = bool(allow_context and spec.key in MARKET_CONTEXT_SECTIONS
                              and source._explanatory_market_excerpt(spec.key, body))
            if not fitted and not contextual:
                continue
        except ArticleDraftCancelled:
            raise
        except Exception:
            # Optional preselection must leave ordinary summary/recovery
            # behavior available when one deterministic parser cannot fit.
            continue
        ready = bool(fitted and not (contextual and source._summary_needs_market_context(spec.key, body, fitted)))
        eligible.append((contextual, ready, candidate, fitted))
    if allow_context and spec.key in MARKET_CONTEXT_SECTIONS:
        # Among equally substantive market explanations, prefer one whose
        # full original already supports a validated translation. Do not spend
        # two calls rejecting another article before using that same source.
        # An easy bare statistic must still not outrank a real explanation.
        eligible.sort(key=lambda item: item[:2], reverse=True)
    for contextual, ready, candidate, fitted in eligible:
        url = str(candidate['url'])
        original_url = str(candidate.get('originalUrl') or url)
        body = str(candidate['body'])
        selected_urls = {url, original_url}
        remaining = []
        for other in candidates:
            other_urls = {str(other.get("url", "")), str(other.get("originalUrl") or other.get("url", ""))}
            if selected_urls & other_urls:
                continue
            selected_urls.update(other_urls)
            remaining.append(other)
        result = {**candidate, "alternatives": remaining,
                  "sourceMethod": candidate.get("sourceMethod", article.get("sourceMethod", "naver")),
                  "_candidateLinksSearched": bool(article.get("_candidateLinksSearched"))}
        result.pop('_nativeReadySummary', None)
        if ready:
            result['_nativeReadySummary'] = (spec.key, body, fitted)
            # This path can publish immediately without summarize_article().
            # Its displayed evidence must therefore also follow the exact
            # validated statement, not an old introductory display excerpt.
            result['briefBody'] = source._native_source_excerpt(body, fitted)
        return result
    return article


def _article_identity_urls(article: dict[str, Any]) -> frozenset[str]:
    """Compare original/Naver aliases without changing the public source URL."""
    identities = set()
    for field in ('url', 'originalUrl', 'publicNewsUrl', 'originallink', 'link'):
        parsed = urlparse(str(article.get(field, '')))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            continue
        host = re.sub(r'^(?:www\.|m\.)', '', parsed.hostname.lower())
        query = parse_qs(parsed.query)
        if host in ('news.naver.com', 'n.news.naver.com'):
            match = re.search(r'/(?:mnews/)?article/(\d+)/(\d+)', parsed.path)
            oid = match[1] if match else query.get('oid', [''])[0]
            aid = match[2] if match else query.get('aid', [''])[0]
            if oid and aid:
                identities.add(f'naver:{oid}:{aid}')
                continue
        params = sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                        if not key.lower().startswith('utm_') and key.lower() not in
                        ('fbclid', 'gclid', 'ref', 'referrer', 'from', 'output', 'amp'))
        path = unquote(parsed.path).rstrip('/') or '/'
        identities.add(host + path + ('?' + urlencode(params) if params else ''))
    return frozenset(identities)


def _article_identity_text(value: Any) -> str:
    return re.sub(r'[^0-9a-z가-힣]', '', unicodedata.normalize('NFKC', str(value)).lower())


def _same_domestic_article(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Identify the same article/reprint, not merely the same market topic."""
    if _article_identity_urls(first) & _article_identity_urls(second):
        return True
    titles = [_article_identity_text(item.get('title', '')) for item in (first, second)]
    bodies = [_article_identity_text(item.get('body', ''))[:2400] for item in (first, second)]
    if min(map(len, bodies)) >= 160 and bodies[0] == bodies[1]:
        return True  # A syndicated original may have a different headline.
    same_title = min(map(len, titles)) >= 20 and titles[0] == titles[1]
    same_outlet = bool(first.get('publisher') and
                       _article_identity_text(first['publisher']) == _article_identity_text(second.get('publisher', '')))
    if same_title and same_outlet:
        return True
    # Distinct reports about the same policy may share a country, figures and
    # topic. Require both an almost identical headline and substantial matching
    # original wording before treating different outlets as a reprint.
    return bool(min(map(len, titles)) >= 20 and min(map(len, bodies)) >= 160
                and SequenceMatcher(None, titles[0], titles[1], autojunk=False).ratio() >= .94
                and SequenceMatcher(None, bodies[0], bodies[1], autojunk=False).ratio() >= .88)


def _verified_summary_alternatives(article: dict[str, Any], spec: SectionSpec,
                                   start: date, end: date,
                                   shared: list[dict[str, Any]],
                                   excluded: tuple[dict[str, Any], ...] = ()) -> list[dict[str, Any]]:
    """Reuse dated originals, excluding domestic articles assigned elsewhere.

    The new species is revalidated against the full original. Sharing is only
    between domestic sections, never an inference about a foreign publisher's
    home country. Prefer a grounded native statement over another model retry.
    """
    seen = {str(article["url"]), str(article.get("originalUrl") or article["url"])}
    suitable = []
    existing = article.get("alternatives", []) + article.get("_candidateLinkOriginals", [])
    for candidate, trusted in chain(((item, True) for item in existing),
                                    ((item, False) for item in shared if spec.domestic)):
        published = candidate.get("publishedDate")
        url = str(candidate.get("url", ""))
        original_url = str(candidate.get("originalUrl") or url)
        if (url in seen or original_url in seen or urlparse(url).scheme not in ("http", "https")
                or urlparse(original_url).scheme not in ("http", "https")
                or not isinstance(published, date) or not start <= published <= end
                or len(str(candidate.get("body", ""))) < 100
                or _relevance(candidate, spec, trusted_country=trusted) < 0):
            continue
        if spec.domestic and (any(_same_domestic_article(candidate, other) for other in excluded)
                              or _same_domestic_article(candidate, article)
                              or any(_same_domestic_article(candidate, item[1]) for item in suitable)):
            continue
        seen.add(url)
        seen.add(original_url)
        native = source._native_report_sentence(spec.key, str(candidate["body"]))
        editorial = bool(spec.key in MARKET_CONTEXT_SECTIONS and source._explanatory_market_excerpt(spec.key, str(candidate['body'])))
        suitable.append(((editorial, bool(native)), candidate))
    suitable.sort(key=lambda entry: entry[0], reverse=True)
    return [{**candidate, "sourceMethod": candidate.get("sourceMethod", article.get("sourceMethod", "search"))}
            for _, candidate in suitable[:2]]


def collect_weekly_livestock_report_draft(report_date: date, progress: Callable[..., None] | None = None,
                                        *, cancel_event: Event | None = None) -> dict[str, Any]:
    """Cancel this collector and its child pools without affecting other callers."""
    with article_cancellation_scope(cancel_event):
        return _collect_weekly_livestock_report_draft(report_date, progress)


def _collect_weekly_livestock_report_draft(report_date: date, progress: Callable[..., None] | None) -> dict[str, Any]:
    """Parallel source discovery, serialized local inference, incremental results."""
    start, end = source.report_article_window(report_date)
    model = source._ensure_ollama_ready()
    sections = {s.key: {"label": s.label, "article": None, "errors": [], "status": "finding", "retryCount": 0,
                       "diagnostics": {"sourceSeconds": 0.0, "summarySeconds": 0.0,
                                       "modelCalls": 0, "modelSeconds": 0.0, "alternativeAttempts": 0,
                                       "validationReasons": [], "promptTokens": 0, "generatedTokens": 0}}
                for s in SECTION_SPECS}
    run_model_budget = source.ArticleRunModelBudget(max_seconds=180.0)
    model_budgets = {s.key: source.ArticleModelBudget(max_calls=2, max_seconds=45.0,
                                                     run_budget=run_model_budget) for s in SECTION_SPECS}
    state_lock = Lock()
    sources_done = set()
    summaries_done = set()
    candidate_futures = []
    candidate_jobs = {}
    domestic_originals: dict[str, dict[str, Any]] = {}
    domestic_selections: dict[str, dict[str, Any]] = {}
    domestic_dedup_searches: set[str] = set()

    def other_domestic_selections(key):
        with state_lock:
            return tuple(article for other, article in domestic_selections.items() if other != key)

    def choose_unique_domestic(key, article):
        """Reserve one verified original before publishing or running inference.

        Domestic completion is serialized in the main collection loop. Foreign
        direct summaries remain parallel; source/enrichment workers only add
        evidence and never claim another section's domestic original.
        """
        spec = SPECS_BY_KEY[key]
        with state_lock:
            shared = list(domestic_originals.values())
        excluded = other_domestic_selections(key)
        pool = [article] + article.get('alternatives', []) + article.get('_candidateLinkOriginals', []) + shared
        valid = []
        for candidate in pool:
            check_article_cancelled()
            published = candidate.get('publishedDate')
            body = str(candidate.get('body', ''))
            if (not isinstance(published, date) or not start <= published <= end
                    or not _article_identity_urls(candidate)
                    or any(urlparse(str(candidate.get(field) or candidate.get('url', ''))).scheme not in ('http', 'https')
                           or not urlparse(str(candidate.get(field) or candidate.get('url', ''))).hostname
                           for field in ('url', 'originalUrl'))
                    or candidate.get('searchResult') or candidate.get('headlineOnly')
                    or len(body) < 100 or len(re.findall(r'[가-힣]', body)) < 30
                    or candidate.get('sourceLanguage', 'ko') != 'ko'
                    or _relevance(candidate, spec, trusted_country=False) < 0
                    or any(_same_domestic_article(candidate, other) for other in excluded)
                    or any(_same_domestic_article(candidate, other) for other in valid)):
                continue
            valid.append(candidate)
        if not valid:
            return None
        # Keep a multi-species fallback available for the section that has no
        # narrower source. A validated pork-only report should not lose to an
        # equally ready general trade article merely because it was found last.
        domestic_specs = [item for item in SECTION_SPECS if item.domestic]
        valid.sort(key=lambda candidate: (
            sum(_relevance(candidate, item, trusted_country=False) >= 0 for item in domestic_specs),
            -_relevance(candidate, spec, trusted_country=False)))
        selected = _prefer_native_summary_candidate(
            {**valid[0], 'alternatives': valid[1:], '_candidateLinkOriginals': [],
             '_candidateLinksSearched': bool(article.get('_candidateLinksSearched'))},
            spec, start, end, bool(model['available']))
        with state_lock:
            domestic_selections[key] = selected
        return selected

    def resolve_domestic_selection(key, article):
        selected = choose_unique_domestic(key, article)
        if selected:
            return selected
        # Reuse this section's already-running bounded enrichment first. It
        # may have downloaded a different valid article while another section
        # reserved the original. Do not duplicate that network work.
        with state_lock:
            pending = candidate_jobs.get(key)
        if pending is not None:
            while True:
                check_article_cancelled()
                try:
                    pending.result(timeout=.2)
                    break
                except FutureTimeoutError:
                    continue
                except ArticleDraftCancelled:
                    raise
                except Exception:
                    break
            selected = choose_unique_domestic(key, article)
            if selected:
                return selected
        if key in domestic_dedup_searches:
            return None
        domestic_dedup_searches.add(key)
        excluded = other_domestic_selections(key)
        excluded_urls = {str(item.get(field, '')) for item in (article,) + excluded
                         for field in ('url', 'originalUrl', 'publicNewsUrl') if item.get(field)}
        started = monotonic()
        try:
            other = _search_article(SPECS_BY_KEY[key], start, end, exclude_urls=frozenset(excluded_urls))
        except ArticleDraftCancelled:
            raise
        except Exception:
            other = None
        finally:
            with state_lock:
                sections[key]['diagnostics']['sourceSeconds'] += monotonic() - started
        if other:
            selected = choose_unique_domestic(key, {**other, '_candidateLinksSearched': True})
            if selected:
                with state_lock:
                    sections[key]['diagnostics']['alternativeAttempts'] += 1
                return selected
        return None

    def emit(stage, message):
        check_article_cancelled()
        if progress:
            with state_lock:
                progress(stage=stage, progress=min(98, int((len(sources_done) + len(summaries_done)) / 24 * 98)),
                         message=message, sections={k: {**v, "diagnostics": dict(v["diagnostics"])} for k, v in sections.items()},
                         candidatesFound=sum(v["article"] is not None for v in sections.values()),
                         readyCount=sum(bool(v.get("summary")) for v in sections.values()), totalCount=12)

    def enrich_candidates(key, candidate):
        started = monotonic()
        try:
            links = _candidate_links(candidate, SPECS_BY_KEY[key], start, end)
        except ArticleDraftCancelled:
            raise
        except Exception:
            links = []
            candidate["_candidateLinksSearched"] = True
        finally:
            with state_lock:
                sections[key]["diagnostics"]["sourceSeconds"] += monotonic() - started
        check_article_cancelled()
        with state_lock:
            if SPECS_BY_KEY[key].domestic:
                for original in candidate.get("_candidateLinkOriginals", []):
                    domestic_originals[str(original["url"])] = original
            if sections[key].get("article", {}).get("url") == candidate["url"]:
                sections[key].update(candidateLinks=links, candidateLinksStatus="completed")
        emit(3, f"{SPECS_BY_KEY[key].label} · 추가 후보 확인 완료")

    def summarize_article(key, article):
        started = monotonic()
        budget = model_budgets[key]
        try:
            if model['available'] and key in MARKET_CONTEXT_SECTIONS and not article.get('_nativeReadySummary'):
                # The already-running link enrichment can finish just after
                # discovery returns. Give that same work a short grace period
                # before spending two inference calls on a model-only source.
                # Never start another search or wait for a slow optional crawl.
                with state_lock:
                    pending_candidates = candidate_jobs.get(key)
                if pending_candidates is not None:
                    try:
                        pending_candidates.result(timeout=.75)
                    except FutureTimeoutError:
                        pass
                    except ArticleDraftCancelled:
                        raise
                    except Exception:
                        pass  # Optional links must not invalidate the original.
                check_article_cancelled()
                article = _prefer_native_summary_candidate(
                    article, SPECS_BY_KEY[key], start, end, True)
            if SPECS_BY_KEY[key].domestic:
                # Recovery can supply an already prepared native brief. It
                # must reserve its NEW original too, not retain the failed
                # primary's reservation merely because no inference remains.
                # Never fall back to a conflicting input after selection fails.
                article = choose_unique_domestic(key, article)
                if article is None:
                    raise source.ArticleDigestError('다른 축종에 이미 선정된 동일 기사입니다. 별도 원문 확인이 필요합니다.')
            with source.article_model_budget(budget):
                prepared = article.get("_nativeReadySummary")
                ready = prepared[2] if prepared and prepared[:2] == (key, str(article["body"])) else None
                native = ready or source._native_report_sentence(key, str(article["body"]))
                if (model['available'] and source._explanatory_market_excerpt(key, str(article['body']))
                        and (not native or source._summary_needs_market_context(key, str(article['body']), native))):
                    # The focused original, not a bare native statistic, is
                    # translated within the same existing per-item budget.
                    summary = source._summarize_report_sentence(key, str(article['title']), str(article['body']))
                else:
                    summary = ready or (source._fit_report_summary(native, key, str(article["body"])) if native else None) or source._summarize_report_sentence(
                        key, str(article["title"]), str(article.get("briefBody") or article["body"]))
            check_article_cancelled()
            if native and summary == source._fit_report_summary(native, key, str(article['body'])):
                article = {**article, "briefBody": source._native_source_excerpt(str(article["body"]), summary)}
            elif key in MARKET_CONTEXT_SECTIONS:
                article = {**article, 'briefBody': source._explanatory_market_excerpt(key, str(article['body'])) or str(article.get('briefBody') or article['body'])}
            return article, summary
        finally:
            with state_lock:
                sections[key]["diagnostics"]["summarySeconds"] += monotonic() - started
                sections[key]["diagnostics"]["modelCalls"] = budget.calls
                sections[key]["diagnostics"]["modelSeconds"] = budget.seconds
                sections[key]["diagnostics"]["validationReasons"] = list(budget.validation_failures)
                sections[key]["diagnostics"]["promptTokens"] = budget.prompt_tokens
                sections[key]["diagnostics"]["generatedTokens"] = budget.generated_tokens

    def recover_summary(key, article):
        spec = SPECS_BY_KEY[key]
        seen = {str(article["url"]), str(article.get("originalUrl") or article["url"])}
        with state_lock:
            shared = list(domestic_originals.values())
            candidate_job = candidate_jobs.get(key)
        alternatives = _verified_summary_alternatives(article, spec, start, end, shared,
                                                       other_domestic_selections(key) if spec.domestic else ())
        budget = model_budgets[key]
        allow_model = budget.calls < budget.max_calls and budget.remaining_seconds() > 0.25

        def ready_native_candidates(candidates):
            # An exhausted model may still reuse a fully validated original.
            # A parser match alone is not proof that its brief fits the page.
            ready = []
            for candidate in candidates:
                original = {**candidate, 'alternatives': [], '_candidateLinkOriginals': []}
                original.pop('_nativeReadySummary', None)
                prepared = _prefer_native_summary_candidate(original, spec, start, end, False)
                if prepared.get('_nativeReadySummary'):
                    ready.append(prepared)
            return ready

        if not allow_model:
            # Exhausted inference cannot be repaired by downloading more
            # non-native articles. An existing enrichment may nevertheless
            # be about to supply a verified original; wait for that same job
            # below before deciding that no native recovery is available.
            alternatives = ready_native_candidates(alternatives)
        # Wait outside the state lock: enrichment may already be downloading
        # the one supplemental search needed for both links and recovery.
        if not alternatives and candidate_job is not None:
            while True:
                check_article_cancelled()
                try:
                    candidate_job.result(timeout=.2)
                    break
                except FutureTimeoutError:
                    continue
            with state_lock:
                shared = list(domestic_originals.values())
            alternatives = _verified_summary_alternatives(article, spec, start, end, shared,
                                                           other_domestic_selections(key) if spec.domestic else ())
            if not allow_model:
                alternatives = ready_native_candidates(alternatives)
        if not allow_model and not alternatives:
            return None  # Never launch another search after inference is exhausted.
        if not alternatives and not article.get("_candidateLinksSearched", False):
            article["_candidateLinksSearched"] = True
            started = monotonic()
            try:
                alternate = _search_article(spec, start, end, exclude_urls=frozenset(seen))
            finally:
                with state_lock:
                    sections[key]["diagnostics"]["sourceSeconds"] += monotonic() - started
            if alternate:
                alternatives = _verified_summary_alternatives(
                    {**article, "alternatives": [{**alternate, "sourceMethod": "naver" if spec.domestic else "search"}]
                     + alternate.get("alternatives", [])}, spec, start, end, [],
                    other_domestic_selections(key) if spec.domestic else ())
        if not alternatives:
            return None
        check_article_cancelled()
        with state_lock:
            sections[key]["diagnostics"]["alternativeAttempts"] += 1
            sections[key]["retryCount"] += 1
        try:
            alternate, summary = summarize_article(key, alternatives[0])
            return alternate, summary
        except ArticleDraftCancelled:
            raise
        except source.ArticleDigestError:
            return None

    def find_unit(keys):
        started = monotonic()
        try:
            check_article_cancelled()
            if keys == ("us", "us_pork"):
                try:
                    found = _usmef_pair(start, end)
                except source.ArticleDigestError:
                    found = {}
                for key in keys:
                    check_article_cancelled()
                    if key not in found:
                        try:
                            fallback = _search_article(SPECS_BY_KEY[key], start, end)
                        except ArticleDraftCancelled:
                            raise
                        except Exception:
                            fallback = None
                            with state_lock:
                                sections[key]["errors"] = ["보완 검색에서 기사 원본을 확인하지 못했습니다."]
                        if fallback:
                            found[key] = {**fallback, "sourceMethod": "search"}
            else:
                candidate = _find_section(SPECS_BY_KEY[keys[0]], start, end)
                found = {keys[0]: candidate} if candidate else {}
            # Do not share mutable recovery state across sections or cached
            # discovery results, even when a test/publisher returns one dict.
            found = {key: {**candidate, "alternatives": list(candidate.get("alternatives", []))}
                     for key, candidate in found.items()}
            found = {key: _broaden_editorial_candidate(candidate, SPECS_BY_KEY[key], start, end)
                     for key, candidate in found.items()}
            found = {key: _prefer_native_summary_candidate(candidate, SPECS_BY_KEY[key], start, end, bool(model['available']))
                     for key, candidate in found.items()}
            for key, candidate in found.items():
                prepared = candidate.get("_nativeReadySummary")
                if prepared and prepared[:2] == (key, str(candidate["body"])):
                    candidate["briefBody"] = source._native_source_excerpt(str(candidate["body"]), prepared[2])
            check_article_cancelled()
            with state_lock:
                for key in keys:
                    candidate = found.get(key)
                    if candidate and SPECS_BY_KEY[key].domestic:
                        for original in [candidate] + candidate.get("alternatives", []):
                            domestic_originals[str(original["url"])] = original
                    sections[key].update(article=source._public_article(candidate),
                                         candidateLinks=candidate.get("candidateLinks", []) if candidate else [],
                                         candidateLinksStatus="finding" if candidate else "completed",
                                         status="found" if candidate else "source_error" if sections[key]["errors"] else "no_article",
                                         sourceMethod=candidate.get("sourceMethod") if candidate else None)
                    prepared = candidate.get("_nativeReadySummary") if candidate else None
                    if (prepared and prepared[:2] == (key, str(candidate["body"]))
                            and not SPECS_BY_KEY[key].domestic):
                        # Verified direct summaries can appear while another
                        # section is still waiting on slow local inference.
                        # Domestic originals are reserved in the serialized
                        # loop first so parallel finds cannot publish twice.
                        sections[key].update(summary=prepared[2], status="completed")
                        summaries_done.add(key)
                    sources_done.add(key)
            emit(2, f"원문 확인 {len(sources_done)}/12 · {SPECS_BY_KEY[keys[0]].label}")
            for key, candidate in found.items():
                candidate_job = submit_article_task(executor, enrich_candidates, key, candidate)
                with state_lock:
                    candidate_jobs[key] = candidate_job
                    candidate_futures.append(candidate_job)
            return found
        except ArticleDraftCancelled:
            raise
        except Exception as error:
            # Sanitized errors only; never propagate request headers/credentials.
            detail = str(error) if isinstance(error, SourceUnavailable) else "기사 원본을 확인하지 못했습니다."
            with state_lock:
                for key in keys:
                    sections[key].update(status="source_error", errors=[detail])
                    sources_done.add(key)
            emit(2, f"원문 확인 {len(sources_done)}/12")
            return {}
        finally:
            with state_lock:
                for key in keys:
                    sections[key]["diagnostics"]["sourceSeconds"] += monotonic() - started

    emit(1, "12개 항목의 주간 기사 후보를 찾고 있습니다.")
    units = [("us", "us_pork")] + [(s.key,) for s in SECTION_SPECS if s.key not in ("us", "us_pork")]
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="livestock-source") as executor:
        futures = [submit_article_task(executor, find_unit, unit) for unit in units]
        # The first unit may OCR the shared US report. Avoid running CPU local
        # inference before it finishes; other HTTP tasks run concurrently.
        for future in chain((futures[0],), as_completed(futures[1:])):
            check_article_cancelled()
            found = future.result()
            keys = units[futures.index(future)]
            for key in keys:
                check_article_cancelled()
                article = found.get(key)
                if article and SPECS_BY_KEY[key].domestic:
                    article = resolve_domestic_selection(key, article)
                    if not article:
                        with state_lock:
                            sections[key].update(status='summary_error',
                                summaryError='다른 축종에 이미 선정된 동일 기사입니다. 해당 주차의 별도 공개 원문을 확보하지 못했습니다.')
                            summaries_done.add(key)
                        emit(3, f"{SPECS_BY_KEY[key].label} · 중복되지 않는 원문 확인 필요")
                        continue
                    with state_lock:
                        sections[key]['article'] = source._public_article(article)
                with state_lock:
                    already_ready = bool(sections[key].get("summary"))
                if already_ready:
                    continue
                # Exact parser rules need original context (e.g. 1kg before a
                # price range, or Denmark before an EU statistic). The AI still
                # receives only the focused passage; no search snippet is used.
                native = (article.get("_nativeReadySummary") or (None, None, None))[2] if article else None
                native = native or (source._native_report_sentence(key, str(article["body"])) if article else None)
                if article and (model["available"] or native):
                    with state_lock:
                        sections[key]["status"] = "summarizing"
                    emit(3, f"{SPECS_BY_KEY[key].label} · 한국어 보고체 요약 중")
                    try:
                        summarized_article, summary = summarize_article(key, article)
                        with state_lock:
                            sections[key].update(summary=summary, status="completed")
                            sections[key]['article'] = source._public_article(summarized_article)
                    except ArticleDraftCancelled:
                        raise
                    except source.ArticleDigestError as error:
                        if isinstance(error, source.ArticleSummaryLayoutError):
                            with state_lock:
                                sections[key].update(summaryError=str(error), status="summary_error")
                                domestic_selections.pop(key, None)
                                summaries_done.add(key)
                            emit(3, f"항목 처리 {len(summaries_done)}/12 · 초안 {sum(bool(v.get('summary')) for v in sections.values())}건 완료")
                            continue
                        # Reuse suitable verified originals before asking
                        # discovery to repeat expensive network searches.
                        emit(3, f"{SPECS_BY_KEY[key].label} · 다른 원문으로 요약 재시도")
                        alternate = None
                        try:
                            recovered = recover_summary(key, article)
                            if recovered:
                                alternate, summary = recovered
                                # Link derivation is local and must not hold
                                # the state lock through optional discovery.
                                links = _candidate_links(
                                    {**alternate, "alternatives": [article] + article.get("alternatives", [])
                                     + article.get("_candidateLinkOriginals", []) + alternate.get("alternatives", [])},
                                    SPECS_BY_KEY[key], start, end, search_missing=False)
                                with state_lock:
                                    sections[key].update(article=source._public_article(alternate), summary=summary,
                                                         candidateLinks=links,
                                                         candidateLinksStatus="completed",
                                                         sourceMethod=alternate.get("sourceMethod", article.get("sourceMethod", "search")),
                                                         status="completed")
                        except ArticleDraftCancelled:
                            raise
                        except Exception:
                            alternate = None
                        if not alternate:
                            with state_lock:
                                sections[key].update(summaryError=str(error), status="summary_error")
                    except Exception:
                        with state_lock:
                            sections[key].update(summaryError="AI 요약 응답을 확인하지 못했습니다.", status="summary_error")
                elif article:
                    with state_lock:
                        sections[key].update(summaryError=model["message"], status="model_unavailable")
                with state_lock:
                    if SPECS_BY_KEY[key].domestic and sections[key].get('status') != 'completed':
                        domestic_selections.pop(key, None)
                    summaries_done.add(key)
                emit(3, f"항목 처리 {len(summaries_done)}/12 · 초안 {sum(bool(v.get('summary')) for v in sections.values())}건 완료")
        for candidate_future in as_completed(candidate_futures):
            check_article_cancelled()
            candidate_future.result()
    # Late optional enrichment may contain the primary article reserved for a
    # different domestic section. Keep only genuinely different alternatives;
    # this final local pass neither downloads nor summarizes another article.
    for key, section in sections.items():
        if SPECS_BY_KEY[key].domestic and section.get('article'):
            with state_lock:
                selected = domestic_selections.get(key)
                selected_originals = tuple(domestic_selections.values())
                shared = list(domestic_originals.values())
            if selected:
                pool = selected.get('alternatives', []) + selected.get('_candidateLinkOriginals', []) + shared
                alternatives = []
                for candidate in pool:
                    if not any(_same_domestic_article(candidate, other)
                               for other in selected_originals + tuple(alternatives)):
                        alternatives.append(candidate)
                section['candidateLinks'] = _candidate_links(
                    {**selected, 'alternatives': alternatives, '_candidateLinkOriginals': []},
                    SPECS_BY_KEY[key], start, end, search_missing=False)
            else:
                section['candidateLinks'] = [link for link in section.get('candidateLinks', [])
                    if not any(_same_domestic_article(link, other) for other in selected_originals)]
    ready = sum(bool(v.get("summary")) for v in sections.values())
    check_article_cancelled()
    candidates = sum(v["article"] is not None for v in sections.values())
    return {"reportDate": report_date.isoformat(), "weekStart": start.isoformat(), "weekEnd": end.isoformat(),
            "model": model, "sections": sections, "styleVersion": STYLE_VERSION,
            "totalCount": 12, "readyCount": ready, "candidatesFound": candidates,
            "message": f"기사 후보 {candidates}/12건 · 초안 {ready}/12건 완료. 빈 항목은 공개 원문을 확보하지 못했거나 요약 검사를 통과하지 못했습니다. 원문 검토 후 사용하세요."}
