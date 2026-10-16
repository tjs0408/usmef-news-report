"""User-approved report examples: style references, never facts for new weeks.

Reference: six supplied reports dated 2026-08-13 through 2026-09-17.
The file named 20260904 has an internal report heading dated 9.10.
These examples condition prompts; no model weights are trained or changed.
"""

from functools import lru_cache

STYLE_VERSION = "livestock-brief-v19"
MAX_ARTICLE_TRACKING = -20
SUMMARY_MIN_LENGTH = 40
# A one-line HWPX brief has considerably less room than the validation ceiling.
# The ceiling remains an exception for facts/conditions which cannot be safely
# shortened; it is never a request to fill the whole available character count.
SUMMARY_TARGET_LENGTH = 50
SUMMARY_SINGLE_LINE_TARGET = 45
SUMMARY_TWO_LINE_TARGET = 85
TWO_LINE_SECTIONS = frozenset({'us', 'us_chicken'})
# Editorial source quality is independent of the number of available lines.
MARKET_CONTEXT_SECTIONS = frozenset({'us', 'australia', 'us_chicken', 'brazil_chicken'})
SUMMARY_LIMITS = {"us": 95, "australia": 95, "domestic": 80}

# Existing beef keys remain compatible with saved diagnostics. All 12 sections
# below now use the user's six supplied reports, not invented generic examples.
SECTION_AUDIENCES = {
    "us": "미국 소고기 수급 및 가격동향",
    "australia": "호주 소고기 수급 및 가격동향",
    "domestic": "해외 소고기 시장 관련 국내기사",
    "us_pork": "미국 돼지고기 수급 및 가격동향",
    "eu_pork": "EU·독일 돼지고기 수급 및 가격동향",
    "domestic_pork": "해외 돼지고기 시장 관련 국내기사",
    "us_chicken": "미국 닭고기 수급 및 가격동향",
    "brazil_chicken": "브라질 닭고기 수급 및 가격동향",
    "domestic_chicken": "해외 닭고기 시장 관련 국내기사",
    "us_egg": "미국 계란 수급 및 가격동향",
    "japan_egg": "일본 계란 수급 및 가격동향",
    "domestic_egg": "해외 계란 시장 관련 국내기사",
}


def is_domestic_kind(kind: str) -> bool:
    return kind == "domestic" or kind.startswith("domestic_")


SUMMARY_LIMITS.update({key: 80 if is_domestic_kind(key) else 95 for key in SECTION_AUDIENCES})
SUMMARY_MAX_LINES = {key: 2 if key in TWO_LINE_SECTIONS else 1 for key in SECTION_AUDIENCES}


def summary_line_limit(kind: str) -> int:
    """Only the US beef and US chicken briefs may use a second line."""
    return SUMMARY_MAX_LINES[kind]


def summary_target_length(kind: str) -> int:
    return SUMMARY_TWO_LINE_TARGET if summary_line_limit(kind) == 2 else SUMMARY_TARGET_LENGTH


def summary_target_range(kind: str) -> tuple[int, int]:
    # A target is not permission to invent context or a stricter completion gate.
    # Insufficient original evidence may still yield a valid shorter brief.
    return (65, SUMMARY_TWO_LINE_TARGET) if summary_line_limit(kind) == 2 else (SUMMARY_MIN_LENGTH, SUMMARY_TARGET_LENGTH)

STYLE_EXAMPLES = {
    "us": (
        "소고기 가격 상승으로 번식우·송아지 농가는 높은 판매가격의 혜택을 받는 반면, 비육농가·가공업체는 생우가격 상승으로 비용 압박",
        "사육두수 감소로 소고기 공급 부족과 높은 가격이 지속되는 가운데 멕시코산 생우 수입 재개로 중장기 공급 개선 기대",
        "분쇄용 쇠고기 수입을 90일간 30만톤 확대해 현재 시장가격보다 약 25% 낮게 공급 예정",
        "수입 확대 발표 이후 송아지 가격이 하락하면서 농가 번식 의향이 약화돼 장기 생산 회복 지연 우려",
        "바비큐 시즌 종료에도 가을 판매 준비로 쇠고기 수요 지속, 도축업체는 계절적 수요 둔화에 대응해 도축량 축소",
        "8월 쇠고기·송아지고기 CPI 전년동월비 5.9% 상승, 다짐육 7.2%·로스트 8.4%·스테이크 4.0% 상승",
    ),
    "australia": (
        "품질 좋은 송아지 선호가 이어지는 가운데 암송아지 가격 하락",
        "2분기 암소 도축 증가로 번식 기반이 줄어 향후 공급 감소 가능성",
        "가축시장 출하량 전주비 21% 감소와 광범위한 강우가 시장을 지지하며 가격 상승",
        "미국의 브라질산 쇠고기 수입 허용으로 호주산 수출용 저지방 쇠고기 가격 하락",
        "중국·한국의 세이프가드로 쇠고기 수출물량이 감소한 가운데 일본·북미로 물량 재배분",
        "육류 항공수출의 여객기 화물칸 의존도가 높은 가운데 중동 항공사 운항 중단으로 운송비 상승",
    ),
    "domestic": (
        "미국 온라인 육류가격 분석 결과 저탄소 소고기는 일반 제품보다 68.7% 비싸게 판매",
        "폭염·가뭄으로 농축산물 생산이 줄면서 소고기 가격이 전년 6월 대비 11.8% 상승",
        "미국, 수입산 다진 쇠고기 30만톤의 관세를 90일간 면제해 생활물가 완화 추진",
        "미국, 농가의 직접 육류가공 허용 계획을 발표하며 대형 가공업체 중심 구조 개선 추진",
        "한우값 상승으로 수입육 의존이 커진 가운데 미국 소고기 공급은 가뭄·기생충 악재로 압박",
        "브라질은 할랄 인증체계를 운영해 전체 소고기 생산량의 약 30%를 할랄 규격으로 생산",
    ),
}

STYLE_EXAMPLES.update({
    "us_pork": (
        "7월 미국 돼지고기 소비자물가지수는 전월비 1.5% 하락",
        "출하체중 증가로 돼지고기 생산량이 안정적으로 유지되며 공급 안정에 따라 가격 하락",
        "중량 증가로 돼지고기 생산량은 늘었으나 가공용 수요 약화로 가격 상승 제한",
        "멕시코 수출 부진과 외식 수요 둔화로 돼지 뒷다리·삼겹살 가격 약세",
        "돼지 뒷다리·삼겹살 가격 약세가 전체 컷아웃 가격 하락 요인으로 작용",
        "8월 돼지고기 CPI 전년비 0.6% 상승, 뒷다리 4.2% 상승·베이컨 관련 제품 2.3% 하락",
    ),
    "eu_pork": (
        "독일 상반기 돼지고기 생산량은 전년비 0.5% 증가한 220만톤으로 전체 육류 생산의 63.7% 차지",
        "돼지고기 소매가격은 전년비 4.1% 하락, 생돈가격 안정 속 소비자가격 하락세 지속",
        "독일 Z세대의 육류 선호도는 83%이며 축종별 선호는 닭고기·소고기·돼지고기 순",
        "독일 상반기 돼지고기 및 부산물 수출량은 약 108만톤으로 전년비 1.7% 증가",
        "독일 1~7월 돼지 도축두수는 2595만두로 전년 동기비 0.2% 증가",
        "상반기 EU 돼지 도축량은 전년 동기비 1.6% 증가, 덴마크가 가장 큰 증가폭 기록",
    ),
    "domestic_pork": (
        "일본 돼지고기·닭고기 가격이 최고치를 기록한 가운데 소고기 대체 수요 증가",
        "미국 캘리포니아 동물복지법 무력화 법안을 둘러싸고 중국 소유 육가공업체 특혜 논란",
        "한국산 돼지고기의 최대 수출시장인 싱가포르는 신선육 수출 비중이 70% 이상 차지",
        "전쟁 여파로 경유·비료비가 오른 가운데 사료비 상승이 육류·유제품·달걀 가격 압박",
        "중국에서 돼지 꼬리 소비가 줄어든 가운데 새끼돼지 단미 등 양돈업 사육방식 영향",
        "북한은 ASF 발병 이후 돼지 사육두수가 급감해 닭·오리고기와 인조고기로 대체",
    ),
    "us_chicken": (
        "도축 데이터 반영으로 미국 닭고기 생산량 전망 상향, 파운드당 가격 전망은 하향",
        "주간 닭고기 생산량이 안정적인 가운데 소매 판촉 확대로 소비자가격 부담 완화",
        "도축량과 중량 증가로 미국 즉석조리용 닭고기 생산량이 4.5% 늘며 평균가격 하락",
        "미국 육계 종란 입란수는 전주비 감소했으나 전년 동기비 소폭 증가",
        "미국 육계 종란 입란수는 2억4895만3천개로 전주비 감소, 전년 동기비 1% 증가",
        "미국 육계 종란 입란수는 2억4572만2천개로 전주비 감소, 전년 동기비 2% 증가",
    ),
    "brazil_chicken": (
        "급여 지급 시기와 개학에 따른 수요 증가로 브라질 국내 닭고기 가격 반등",
        "브라질 국내 수요 회복과 적정 재고로 닭고기 가격 반등 후 안정세",
        "브라질 닭고기 수출량이 전년비 증가, 전년 조류인플루엔자 수입 제한의 기저효과 영향",
        "EU가 위생기준 준수를 보장할 때까지 브라질산 가금류·쇠고기 수입 중단 예정",
        "브라질 8월 닭고기 수출량은 49만2천톤으로 전년비 24.8% 증가",
        "EU가 브라질의 가금류 위생 관련 절차를 수용해 닭고기 수출 재개 전망",
    ),
    "domestic_chicken": (
        "이란 경제가 생존체제로 전환한 가운데 닭고기·우유 가격이 전년비 급등",
        "벨라루스에서 긴 겨울과 고령화로 영양 관심이 늘며 닭고기 등 건강 간편식 인기",
        "닭고기는 경제성과 기술·유통 혁신, 무역망 및 다양한 소비로 세계 식탁에서 확대",
        "이란의 물가상승률이 급등한 가운데 달걀·닭고기 등 식료품 가격 상승",
        "아르헨티나의 1인당 닭고기 소비가 소고기를 넘어선 가운데 고단백 식품 관심 증가",
        "베트남 가금육·부산물 수입 평균가격은 kg당 약 1달러로 채소보다 저렴",
    ),
    "us_egg": (
        "미국 7월 계란 소비자가격은 다스당 2.189달러로 전월비 2.2% 상승",
        "산란계 공급 회복으로 미국 계란 재고가 늘고 도·소매가격 하락",
        "미국 계란 공급 증가로 가격 하락세가 이어졌으나 8월 하순 이후 도매가격 하락폭 축소",
        "미국 계란 수요는 약~보통 수준이며 공급이 충분해 주요 지역 도매가격 하락",
        "미국 계란 공급 회복과 소매업체 판촉 증가로 소비자의 가격 부담 완화",
        "미국 계란 공급량은 보통 수준을 유지하며 케이지 사육 계란 도매가격 하락세",
    ),
    "japan_egg": (
        "일본 계란가격은 하향 안정세이나 고온에 따른 산란율·난중 저하로 공급 부담",
        "일본 산란계 회복에도 생산비 상승과 가공 수요 증가로 높은 계란가격 유지",
        "일본 6월 가계조사에서 닭고기 구매량은 늘고 계란 구매량은 감소",
        "일본의 기록적인 폭염으로 산란율·계란 중량이 줄며 도매가격 상승",
        "일본 츠키미 풍습으로 계란을 활용한 상품 판매 확대",
        "일본 9월 계란가격은 10개당 309엔으로 평년 수준보다 높게 형성",
    ),
    "domestic_egg": (
        "일본은 대형농협, 미국은 기업농이 주도하는 등 국가별 계란 유통구조·가격체계 차이",
        "아마존은 미국 드론 배송을 확대하며 계란·신선식품 등 배송 품목 다양화 테스트",
        "영국에서 수입 달걀 관련 살모넬라 감염이 늘며 인증된 영국산 달걀 섭취 권고",
        "계란 생산 회복에도 추석을 앞두고 추가 수입을 추진하며 감축·종료 기준은 미정",
        "LX판토스는 항공기를 활용해 미국·태국산 계란 1120만개를 한국으로 수송",
        "미국에서 식료품값 부담이 커지며 달걀 등을 선구매 후결제로 구입하는 소비 증가",
    ),
})

# Coverage observed in the supplied reports. These are ranking dimensions, not
# a whitelist of publishers or facts. Foreign domestic briefs cover ALL countries.
EDITORIAL_TOPICS = {
    "price": ("가격", "물가", "소비자", "CPI", "price", "retail", "preço", "価格", "物価"),
    "supply": ("공급", "생산", "도축", "사육", "재고", "산란", "supply", "production", "slaughter", "yarding", "供給", "生産"),
    "trade": ("수입", "수출", "관세", "교역", "검역", "import", "export", "tariff", "exporta", "輸入", "輸出"),
    "demand": ("수요", "소비", "선호", "구매", "외식", "가공", "demand", "consumption", "需要", "消費"),
    "cost_risk": ("생산비", "사료", "운송", "배송", "유통", "폭염", "가뭄", "질병", "살모넬라", "cost", "feed", "drought", "flu", "delivery", "猛暑", "鳥インフル"),
    "policy_labor": ("정책", "이민", "단속", "근로자", "인력", "규제", "immigration", "enforcement", "labor", "labour", "worker", "policy"),
}

# Only reviewed paraphrases enter few-shot context. Full archive text remains
# private work material; old report dates/numbers never qualify a new article.
from .report_reference_corpus import historical_style_examples
for _kind in SECTION_AUDIENCES:
    STYLE_EXAMPLES[_kind] = tuple(dict.fromkeys((*STYLE_EXAMPLES[_kind], *historical_style_examples(_kind))))


@lru_cache(maxsize=128)
def _one_line_reference_example(kind: str, sentence: str) -> bool:
    # The layout module imports the constants above. Import it only after this
    # module has finished loading, and cache the fixed historical examples.
    from .article_hwpx_layout import summary_reference_layout

    return bool(summary_reference_layout(sentence, kind)['withinLineLimit'])


def reference_examples(kind: str, context: str = "") -> tuple[str, ...]:
    """Retrieve up to two topic-matched examples that respect the line policy."""
    themes = [terms for terms in EDITORIAL_TOPICS.values() if any(term.casefold() in context.casefold() for term in terms)]
    def editorial_score(sentence: str) -> int:
        if kind not in TWO_LINE_SECTIONS:
            return 0
        # Prefer the historical event -> market consequence form, rather than
        # selecting another bare production total because it shares a keyword.
        domains = sum(any(term.casefold() in sentence.casefold() for term in terms)
                      for terms in EDITORIAL_TOPICS.values())
        connected = any(term in sentence for term in ('가운데', '반면', '따른', '따라', '영향', '우려', '압박', '으로', '여파'))
        return int(domains >= 2 and connected) * 3 + int(60 <= len(sentence) <= 85)
    ranked = sorted(enumerate(STYLE_EXAMPLES[kind]),
                    key=lambda pair: (editorial_score(pair[1]), sum(any(term.casefold() in pair[1].casefold() for term in terms) for terms in themes), pair[0]), reverse=True)
    if summary_line_limit(kind) == 1:
        ranked = [(index, sentence) for index, sentence in ranked
                  if _one_line_reference_example(kind, sentence)]
    return tuple(sentence for _, sentence in ranked[:2])


def style_prompt(kind: str, context: str = "") -> str:
    examples = reference_examples(kind, context)
    target_minimum, target_maximum = summary_target_range(kind)
    two_lines = summary_line_limit(kind) == 2
    line_rule = (
        " 이 항목은 소·닭 현지동향이므로 최대 두 줄을 허용합니다. 단순 주간 생산량 한 개를 반복하기보다 같은 원문에 명시된 정책·수요·공급 변화와 그 원인 또는 시장 영향을 함께 정리하세요. 설명 근거가 없으면 추정하거나 두 줄을 채우려고 문구를 늘리지 마세요."
        if two_lines else
        " 이 항목의 요약은 반드시 한 줄에 맞춰야 합니다. 두 줄은 허용하지 않으므로 반복 설명을 덜어낸 완결형으로 간결하게 다시 구성하세요."
    )
    return (
        "아래는 보고체 문장 형식 참고 예시입니다. 예시의 수치·사건은 이번 기사 근거가 아니므로 복사하지 마세요. 예시 길이가 아니라 아래의 이번 길이 목표를 따르세요.\n"
        + "\n".join(f"문체 예시: {sentence}" for sentence in examples)
        + f"\n이번 결과의 요약 본문은 공백 포함 {SUMMARY_MIN_LENGTH}~{SUMMARY_LIMITS[kind]}자, 한 가지 시장 이슈만 선택하세요."
        + (f" 한글 보고서 두 줄 분량인 {target_minimum}~{target_maximum}자를 목표로, 근거가 연결된 핵심 사실 두 가지를 한 문장으로 정리하세요."
           if two_lines else f" 한글 보고서 한 줄에 맞도록 우선 {SUMMARY_MIN_LENGTH}~{SUMMARY_TARGET_LENGTH}자를 목표로 하고, 수치가 적으면 40~45자로 정리하세요.")
        + " 긴 문장이나 서로 다른 이슈를 합치지 말고 국가·축종과 핵심 변화부터 바로 쓰세요."
        + " 조사·반복 주체·'흐름을 보이는 가운데' 같은 상투어를 줄이되, 수치의 단위·비교기간·부정·승인 대기·전망 여부는 반드시 보존하세요."
        + " 글자 수를 줄이려고 단어를 붙이거나 필요한 띄어쓰기를 없애지 마세요. '전주비 5%', '4억 3000만 파운드', '363만 2000마리', '1억 8968만 9000마리', '역대 최고치'처럼 자연스럽게 띄어 쓰세요."
        + f" 요약은 자간 0에서 시작하며 필요한 경우에만 최저 {MAX_ARTICLE_TRACKING}까지 조정하는 문서에 들어갑니다. 한 줄을 위해 필수 수치나 조건을 없애거나 숫자 묶음을 붙이지 마세요."
        + line_rule
        + " 길이가 조금 넘으면 핵심 사실을 담은 완결형으로 다시 구성하고, 필요하면 비교수치를 괄호로 묶으세요."
        + f" {target_maximum}자를 넘는 것은 필요한 근거·조건을 줄일 수 없을 때만 허용하며, 최대 길이를 채우려고 설명을 덧붙이지 마세요."
        + " 핵심 변화와 원문에 명시된 원인 또는 영향만 연결하고 '상승·하락·확대·축소·기대·우려'처럼 간결한 보고체로 끝내세요."
        + " '이어간다·시사한다·전망된다' 대신 '지속·시사·전망' 같은 명사형으로 끝내세요. 원문에 없는 전망을 만들지 마세요."
        + " 현지동향과 국내기사 모두 개조식으로 작성하세요. '~한다·~했다·~됩니다·~있다' 같은 서술형 종결은 금지합니다. 부정·조건·가능성은 삭제하지 마세요."
        + " 40자보다 짧으면 원문에 있는 주체·기간·규모·직접 원인 등을 보완하고, 반복 표현이나 무의미한 문구로 길이를 늘리지 마세요."
        + " 핵심 수치 1~2개를 우선 보존하고, 세부 품목 나열과 반복 설명은 생략하세요."
        + " 숫자 나열보다 가격·수급의 변화와 그 이유를 우선하되, 원문에 원인·영향이 없으면 추정하지 마세요."
    )
