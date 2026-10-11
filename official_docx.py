"""Checked extraction for simple official DOCX laws; unsupported structures stop ingestion."""
import io
from xml.etree import ElementTree
from zipfile import ZipFile

from law_articles import HEADING, split_articles

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
UNSUPPORTED = {'tbl', 'drawing', 'pict', 'object', 'altChunk', 'footnoteReference',
               'endnoteReference', 'sym', 'ins', 'del', 'txbxContent',
               'oMath', 'oMathPara', 'moveFrom', 'moveTo', 'AlternateContent'}


def extract_docx(payload, title):
    style_numbering = []
    with ZipFile(io.BytesIO(payload)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 50_000_000:
            raise ValueError('不支持超过50MB解压内容的原件')
        if archive.testzip() is not None:
            raise ValueError('DOCX CRC校验失败')
        document = ElementTree.fromstring(archive.read('word/document.xml'))
        if 'word/styles.xml' in archive.namelist():
            styles = ElementTree.fromstring(archive.read('word/styles.xml'))
            style_numbering = list(styles.iter(W + 'numPr'))
            if any(len(prop.findall(W + 'numId')) != 1 or prop.find(W + 'numId').get(W + 'val') != '0'
                   for prop in style_numbering):
                raise ValueError('不支持含编号样式的原件，需检查样式继承与生成编号')
    body = document.find(W + 'body')
    if body is None:
        raise ValueError('DOCX没有正文')
    unsupported = {element.tag.rsplit('}', 1)[-1] for element in body.iter()} & UNSUPPORTED
    numbering = list(body.iter(W + 'numPr'))
    # ISO 29500 / Microsoft NumberingId: numId=0 explicitly removes numbering.
    if any(len(prop.findall(W + 'numId')) != 1 or prop.find(W + 'numId').get(W + 'val') != '0'
           for prop in numbering):
        unsupported.add('numPr')
    unsupported |= {child.tag.rsplit('}', 1)[-1] for child in body
                    if child.tag not in (W + 'p', W + 'sectPr')
                    and not (child.tag in (W + 'bookmarkStart', W + 'bookmarkEnd')
                             and not len(child) and not (child.text or '').strip()
                             and not (child.tail or '').strip())}
    if unsupported:
        raise ValueError('不支持的正文结构：' + ','.join(sorted(unsupported)))
    paragraphs = []
    for paragraph in body.findall(W + 'p'):
        parts = []
        for element in paragraph.iter():
            if element.tag == W + 't':
                parts.append(element.text or '')
            elif element.tag == W + 'tab':
                parts.append('\t')
            elif element.tag in (W + 'br', W + 'cr'):
                parts.append('\n')
        paragraphs.append(''.join(parts))
    expected = ''.join(title.split())
    title_range = None
    # Publication announcements may precede a wrapped title. Never search past an article.
    prefix = []
    for index, paragraph in enumerate(paragraphs[:30]):
        match = HEADING.match(paragraph)
        if match and match.group('article'):
            break
        if paragraph.strip():
            prefix.append((index, ''.join(paragraph.split())))
    for start in range(len(prefix)):
        joined = ''
        for end in range(start, min(start + 5, len(prefix))):
            joined += prefix[end][1]
            if joined == expected:
                title_range = [prefix[start][0], prefix[end][0] + 1]
                break
            if not expected.startswith(joined):
                break
        if title_range is not None:
            break
    if title_range is None:
        raise ValueError('原件正文前标题与官方详情不一致')
    return '\n\n'.join(paragraphs) + '\n', {
        'paragraphs': len(paragraphs), 'nonempty_paragraphs': sum(bool(p.strip()) for p in paragraphs),
        'zip_crc_ok': True, 'unsupported_body_structures': [],
        'disabled_numbering_properties': len(numbering),
        'disabled_style_numbering_properties': len(style_numbering),
        'title_paragraph_range': title_range,
        'scope': '正文顶层段落；不含页眉页脚/版式。表格、绘图、修订、脚注引用等拒绝自动抽取。'}


def article_labels(tree):
    if tree is None:
        return []
    labels = []
    match = HEADING.match(tree.get('title', ''))
    if match and match.group('article'):
        labels.append(''.join(match.group('article').split()))
    for child in tree.get('children', []):
        labels.extend(article_labels(child))
    return labels


def check_articles(text, official_labels, *, allow_missing_catalog=False):
    spans = split_articles(text)
    if ((not official_labels and not allow_missing_catalog)
            or (official_labels and [row['article'] for row in spans] != official_labels)):
        raise ValueError('抽取条号与官方条号目录不一致，拒绝自动入库')
    if not official_labels:
        # Only the registered fixed batch uses this lower-assurance path. A gap or
        # suffix may be legally legitimate, but requires separate review, not guessing.
        def label(number):
            if not 0 < number < 10000:
                raise ValueError('超出连续条号检查范围')
            result, zero = '', False
            for unit, name in ((1000, '千'), (100, '百'), (10, '十'), (1, '')):
                digit, number = divmod(number, unit)
                if digit:
                    result += ('零' if zero else '') + '一二三四五六七八九'[digit - 1] + name
                    zero = False
                elif result and number:
                    zero = True
            if result.startswith('一十'):
                result = result[1:]
            return '第' + result + '条'
        if any(span['article'].replace('〇', '零') != label(index)
               for index, span in enumerate(spans, 1)):
            raise ValueError('缺官方目录且不满足从第一条起的连续条号，需单独核验')
    return {'article_count': len(spans), 'official_labels_match': bool(official_labels),
            'catalog_status': 'matched' if official_labels else 'missing',
            'unassigned_body_content': 0 if official_labels else None,
            'consecutive_numbering_checked': not bool(official_labels),
            'preamble_end': spans[0]['start'], 'articles': spans,
            'legal_completeness_reviewed': False, 'legal_applicability_verified': False}


def normalize_headings(text, tree):
    """Only join intra-paragraph heading soft breaks when its full text matches official TOC."""
    pending, titles = ([] if tree is None else [tree]), set()
    while pending:
        node = pending.pop()
        title = node.get('title', '')
        match = HEADING.match(title)
        if match and match.group('article') is None:
            titles.add(''.join(title.split()))
        pending.extend(node.get('children', []))
    blocks, changes, offset = text.split('\n\n'), [], 0
    for index, original in enumerate(blocks):
        match = HEADING.match(original)
        if ('\n' in original and match and match.group('article') is None
                and ''.join(original.split()) in titles):
            blocks[index] = original.replace('\n', ' ')
            changes.append({'start': offset, 'end': offset + len(original),
                            'original': original, 'normalized': blocks[index],
                            'basis': '官方目录标题忽略空白后逐字相同；只将软换行换成一个空格'})
        offset += len(original) + 2
    return '\n\n'.join(blocks), changes
