"""A literal USMEF pork-price trend and its explicit current supply cause."""
import re
import unicodedata

from .grounded_korean_brief import source_statement_retracted


def native_usmef_pork_price_brief(body: str) -> tuple[str, str] | None:
    text = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(body))).strip()
    if not re.search(r'미국의?\s*돼지고기', text):
        return None
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for index, sentence in enumerate(sentences):
        trend = re.search(r'돼지고기\s*컷아웃\s*가격은.{0,90}?'
                          r'(?P<weeks>\d{1,2})주\s*연속\s*하락세를\s*이어가고\s*있다[.]', sentence)
        if not trend or not 1 <= int(trend['weeks']) <= 52 or source_statement_retracted(text, sentence):
            continue
        for following in sentences[index+1:index+4]:
            cause = re.search(
                r'(?P<quarter>[1-4])분기\s*도축\s*및\s*생산량이\s*본격적으로\s*증가함에\s*따라\s*'
                r'(?P<month>\d{1,2})월\s*들어\s*하락세가\s*한층\s*가팔라졌다[.]', following)
            if (not cause or not 1 <= int(cause['month']) <= 12
                    or (int(cause['month'])-1)//3+1 != int(cause['quarter'])
                    or source_statement_retracted(text, following)):
                continue
            if re.search(r'아니|않|못|부인|정정|가정|예정|검토|전망', sentence + ' ' + following):
                continue
            # Do not publish the article's dollar quote without a denominator
            # when the extracted text does not provide one.
            summary = (f"미국 돼지고기 도매가격 지표 {trend['weeks']}주 연속 하락, "
                       f"생산 증가로 {cause['month']}월 하락 가속")
            return summary, sentence + ' ' + following
    # A weekly percentage plus explicitly named wholesale-cut causes needs
    # no unstated dollars-per-weight denominator. Each part's role is local
    # to this cutout paragraph, never borrowed from the later price table.
    weekly = re.search(
        r'지난주\s*돼지고기\s*컷아웃\s*가격은\s*전주\s*대비\s*'
        r'(?P<rate>\d+(?:\.\d+)?)%\s*\([^)]*\)\s*하락한\s*'
        r'\d+(?:\.\d+)?달러를\s*기록', text)
    cause = re.search(
        r'대분할\s*belly\s*부위\s*가격이\s*전년\s*동기를\s*크게\s*밑돌며\s*'
        r'전체\s*컷아웃\s*가격을\s*끌어내리는\s*주된\s*요인으로\s*작용하고\s*있으며,?\s*'
        r'대분할\s*ham\s*부위\s*역시\s*주요\s*하락\s*요인으로\s*작용하고\s*있다', text, re.I)
    if weekly and cause and 0 < float(weekly['rate']) < 100:
        block = text[weekly.start():cause.end()]
        if 0 <= cause.start() - weekly.end() <= 250 and not re.search(r'부인|정정|아니|않|예정|전망', block):
            summary = (f"미국 돼지고기 도매가격 지표 전주비 {weekly['rate']}% 하락, "
                       "삼겹살·뒷다리 약세 영향")
            return summary, weekly[0] + ' ' + cause[0]
    return None
