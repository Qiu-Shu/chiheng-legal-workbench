"""Conservative, bounded dual-parser extraction of simple text-layer official PDFs."""
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from local_settings import resolve_pdf_python


RUNTIME = None
MAX_BYTES = 10_000_000
MAX_PAGES = 100
MAX_TEXT = 1_000_000
TIMEOUT = 60


def _compact(text):
    return ''.join(text.split())


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _check_input(payload, expected_title):
    if len(payload) > MAX_BYTES:
        raise ValueError('不支持超过10MB的PDF原件')
    if not payload.startswith(b'%PDF-'):
        raise ValueError('原件不是PDF')
    if not isinstance(expected_title, str) or not _compact(expected_title):
        raise ValueError('PDF核验需要非空标题')


def extract_pdf(payload: bytes, expected_title: str) -> tuple[str, dict]:
    """Run the selected Python in a bounded subprocess, preserving parser checks."""
    _check_input(payload, expected_title)
    try:
        result = subprocess.run([str(resolve_pdf_python(RUNTIME)), str(Path(__file__).resolve()), '--worker', expected_title],
                                input=payload, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('PDF抽取超过60秒，拒绝自动入库') from exc
    except OSError as exc:
        raise ValueError('PDF抽取所需Python运行环境不可用') from exc
    if result.returncode:
        raise ValueError('PDF抽取子进程失败：' + result.stderr.decode('utf-8', 'replace')[-1000:])
    try:
        response = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('PDF抽取子进程返回无效结果') from exc
    if 'error' in response:
        raise ValueError(response['error'])
    return response['text'], response['manifest']


def _check_structure(page):
    # With pdfplumber's default laparams=None, LTPage children retain paint order.
    # White rectangles are permitted only if they cannot cover earlier text.
    from pdfminer.layout import LTChar, LTRect
    if page.images or page.annots or page.lines or page.curves:
        raise ValueError('不支持含图片、注释、线条、曲线或表格边框的PDF')
    previous_chars, backgrounds = [], 0
    for obj in page.layout:
        if isinstance(obj, LTChar):
            previous_chars.append(obj)
        elif isinstance(obj, LTRect):
            color = obj.non_stroking_color
            if obj.stroke or not obj.fill or color not in (1, (1, 1, 1), (0, 0, 0, 0)):
                raise ValueError('不支持可见矩形、表格或其他绘图结构')
            for char in previous_chars:
                if (min(obj.x1, char.x1) > max(obj.x0, char.x0)
                        and min(obj.y1, char.y1) > max(obj.y0, char.y0)):
                    raise ValueError('白色矩形覆盖先前文字，需人工检查')
            backgrounds += 1
        else:
            raise ValueError('不支持嵌套绘图、图像或其他PDF布局结构')
    if any(not char.get('upright', False) for char in page.chars):
        raise ValueError('不支持旋转文字')
    # Per-glyph colors already reflect PDF q/Q graphics-state save/restore.
    if any(char.get('non_stroking_color') in (1, (1,), (1, 1, 1), (0, 0, 0, 0))
           for char in page.chars):
        raise ValueError('不支持白色文字，无法确认文字可见性')
    return backgrounds


def _footer(page, number):
    lines = page.extract_text_lines()
    if len(lines) < 2:
        return None
    line = lines[-1]
    value = _compact(line['text'])
    if not re.fullmatch(r'(?:[—–-])?' + str(number) + r'(?:[—–-])?', value):
        return None
    if (line['top'] < page.height * .9
            or abs((line['x0'] + line['x1']) / 2 - page.width / 2) > page.width * .1
            or line['top'] - lines[-2]['bottom'] < max(12, line['bottom'] - line['top'])):
        return None
    return {'text': line['text'],
            'bbox': [line['x0'], line['top'], line['x1'], line['bottom']],
            'basis': '末行、页底10%、水平居中、与正文分离，页码等于物理页序号',
            'removed_from': {}}


def _without_footer(raw, footer, parser):
    if footer is None:
        return raw.strip()
    lines = raw.strip().splitlines()
    value = _compact(footer['text'])
    if lines and _compact(lines[-1]) == value:
        footer['removed_from'][parser] = 'suffix'
        return '\n'.join(lines[:-1]).strip()
    if parser == 'pypdf' and lines and _compact(lines[0]) == value:
        footer['removed_from'][parser] = 'prefix'
        return '\n'.join(lines[1:]).strip()
    raise ValueError('已确认的页脚页码无法在抽取文本端点定位')


def _check_visible_bounds(payload, removed_footer_glyphs=None):
    """Check glyph boxes using pdfminer's transforms; support rectangular clips only."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.utils import apply_matrix_pt
    removed_footer_glyphs = removed_footer_glyphs or {}
    exceptions = []

    def intersection(a, b):
        return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))

    def transformed_box(box, ctm):
        points = [apply_matrix_pt(ctm, (x, y)) for x in (box[0], box[2])
                  for y in (box[1], box[3])]
        return (min(p[0] for p in points), min(p[1] for p in points),
                max(p[0] for p in points), max(p[1] for p in points))

    class BoundsDevice(PDFPageAggregator):
        def begin_page(self, page, ctm):
            super().begin_page(page, ctm)
            self.clip = intersection(transformed_box(page.mediabox, ctm),
                                     transformed_box(page.cropbox, ctm))
            self.page_bounds = self.clip

        def render_char(self, *args, **kwargs):
            advance = super().render_char(*args, **kwargs)
            box = self.cur_item._objs[-1].bbox
            char = self.cur_item._objs[-1].get_text()
            if (not all(math.isfinite(n) for n in (*box, *self.page_bounds))
                    or box[0] < self.page_bounds[0] - 1e-5 or box[1] < self.page_bounds[1] - 1e-5
                    or box[2] > self.page_bounds[2] + 1e-5 or box[3] > self.page_bounds[3] + 1e-5):
                raise ValueError('文字超出页面可视交集')
            # A tiny tolerance only accommodates floating-point arithmetic.
            if (not all(math.isfinite(n) for n in (*box, *self.clip))
                    or box[0] < self.clip[0] - 1e-5 or box[1] < self.clip[1] - 1e-5
                    or box[2] > self.clip[2] + 1e-5 or box[3] > self.clip[3] + 1e-5):
                # Only exact glyphs already removed from BOTH parser bodies may
                # bypass an active clip check. Never relax physical-page bounds.
                known = removed_footer_glyphs.get(self.cur_item.pageid, [])
                if (not all(math.isfinite(n) for n in self.clip)
                        or not any(char == glyph['text'] and all(abs(a-b) <= 1e-5
                                  for a,b in zip(box,glyph['bbox'])) for glyph in known)):
                    raise ValueError('文字超出页面可视交集或当前矩形裁剪范围')
                exceptions.append({'page':self.cur_item.pageid,'text':char,'bbox':box,'clip':self.clip})
            return advance

    class BoundsInterpreter(PDFPageInterpreter):
        def init_state(self, ctm):
            super().init_state(ctm)
            self.clip_stack = []

        def do_q(self):
            self.clip_stack.append(self.device.clip)
            super().do_q()

        def do_Q(self):
            if self.curpath:
                raise ValueError('不支持在裁剪路径中途恢复坐标变换')
            if not self.clip_stack:
                raise ValueError('不支持未配对的裁剪图形状态')
            self.device.clip = self.clip_stack.pop()
            super().do_Q()

        def do_cm(self, a, b, c, d, e, f):
            if self.curpath:
                raise ValueError('不支持在裁剪路径中途修改坐标变换')
            super().do_cm(a, b, c, d, e, f)

        def do_W(self):
            if [part[0] for part in self.curpath] != ['m', 'l', 'l', 'l', 'h']:
                raise ValueError('不支持非单一矩形裁剪路径')
            points = [apply_matrix_pt(self.ctm, part[1:]) for part in self.curpath[:4]]
            xs, ys = {p[0] for p in points}, {p[1] for p in points}
            if (len(xs) != 2 or len(ys) != 2
                    or not all(math.isfinite(n) for p in points for n in p)
                    or set(points) != {(x, y) for x in xs for y in ys}
                    or any(a[0] != b[0] and a[1] != b[1]
                           for a, b in zip(points, points[1:] + points[:1]))):
                raise ValueError('不支持变换后非轴对齐的矩形裁剪路径')
            self.device.clip = intersection(self.device.clip, (min(xs), min(ys), max(xs), max(ys)))

        def do_W_a(self):
            self.do_W()

    manager = PDFResourceManager()
    device = BoundsDevice(manager, laparams=None)
    interpreter = BoundsInterpreter(manager, device)
    try:
        for page in PDFPage.get_pages(io.BytesIO(payload)):
            interpreter.process_page(page)
    finally:
        device.close()
    return exceptions


def _extract_local(payload, expected_title):
    import pdfplumber
    import pypdf
    _check_input(payload, expected_title)
    reader = pypdf.PdfReader(io.BytesIO(payload), strict=True)
    if reader.is_encrypted:
        raise ValueError('不支持加密PDF')
    if not 0 < len(reader.pages) <= MAX_PAGES:
        raise ValueError('PDF须为1至100页')
    if reader.root_object.get('/AcroForm') or reader.root_object.get('/OCProperties'):
        raise ValueError('不支持表单或可选内容层PDF')
    removed_footer_glyphs = {}
    pages, total_chars, offset = [], {'pypdf': 0, 'pdfplumber': 0}, 0
    with pdfplumber.open(io.BytesIO(payload)) as document:
        if len(document.pages) != len(reader.pages):
            raise ValueError('两工具PDF页数不一致')
        for number, (source, page) in enumerate(zip(reader.pages, document.pages), 1):
            # Only the exact observed neutral WPS state is allowed. Extra keys,
            # masks, transfer functions or a non-opaque alpha remain unsupported.
            neutral_states = []
            for name, reference in source.get('/Resources', {}).get('/ExtGState', {}).items():
                state = reference.get_object()
                from pypdf.generic import BooleanObject, FloatObject, NumberObject
                if (set(state) != {'/Type','/AIS','/BM','/CA','/ca'}
                        or state['/Type'] != '/ExtGState' or state['/BM'] != '/Normal'
                        or not isinstance(state['/AIS'],BooleanObject) or state['/AIS'].value is not False
                        or any(not isinstance(state[key],(FloatObject,NumberObject)) or state[key] != 1
                               for key in ('/CA','/ca'))):
                    raise ValueError('不支持非精确中性ExtGState，需确认透明度与文字可见性')
                neutral_states.append(str(name))
            if len(page.chars) > 100_000:
                raise ValueError('PDF单页文字超过10万字符')
            backgrounds = _check_structure(page)
            for operands, operator in source.get_contents().operations if source.get_contents() else []:
                if operator == b'Tr' and operands != [0]:
                    raise ValueError('不支持隐藏、描边或裁剪文字')
            raw = {'pypdf': source.extract_text() or '', 'pdfplumber': page.extract_text() or ''}
            for parser, value in raw.items():
                total_chars[parser] += len(value)
            if max(total_chars.values()) > MAX_TEXT:
                raise ValueError('PDF总文字超过100万字符')
            if any(not _compact(value) for value in raw.values()):
                raise ValueError(f'PDF第{number}页无可用文字层')
            footer = _footer(page, number)
            bodies = {parser: _without_footer(value, footer, parser) for parser, value in raw.items()}
            if _compact(bodies['pypdf']) != _compact(bodies['pdfplumber']):
                raise ValueError(f'PDF第{number}页双工具文字不一致，拒绝猜测补齐')
            if footer:
                x0, top, x1, bottom = footer['bbox']
                removed_footer_glyphs[number] = [
                    {'text':c['text'],'bbox':(c['x0'],c['y0'],c['x1'],c['y1'])}
                    for c in page.chars if c['text'] in '0123456789—–-'
                    and c['x0'] >= x0 and c['x1'] <= x1 and c['top'] >= top and c['bottom'] <= bottom]
            body = bodies['pdfplumber']
            if not _compact(body):
                raise ValueError(f'PDF第{number}页除页码外无正文文字')
            pages.append({'page': number, 'start': offset, 'end': offset + len(body),
                          'body_text': body, 'body_sha256': _sha(body), 'raw_text': raw,
                          'raw_sha256': {parser: _sha(value) for parser, value in raw.items()},
                          'parser_body_text': bodies,
                          'parser_body_sha256': {parser: _sha(value) for parser, value in bodies.items()},
                          'footer': footer, 'white_background_rectangles': backgrounds})
            if neutral_states:
                pages[-1]['verified_neutral_graphics_states'] = sorted(neutral_states)
            offset += len(body) + 2
    text = '\n\n'.join(row['body_text'] for row in pages) + '\n'
    if not _compact(text).startswith(_compact(expected_title)):
        raise ValueError('PDF正文开头标题与官方详情不一致')
    exceptions = _check_visible_bounds(payload, removed_footer_glyphs)
    manifest = {'schema_version': 1, 'format': 'pdf',
                  'source_sha256': hashlib.sha256(payload).hexdigest(), 'text_sha256': _sha(text),
                  'page_count': len(pages), 'pages': pages,
                  'parsers': {'pypdf': pypdf.__version__, 'pdfplumber': pdfplumber.__version__},
                  'canonical_parser': 'pdfplumber', 'offset_unit': 'Python Unicode character',
                  'page_separator': '\n\n', 'trailing_separator': '\n',
                  'title_prefix_matches': True, 'legal_completeness_reviewed': False,
                  'legal_applicability_verified': False, 'visual_reviewed': False,
                  'scope': '仅逐页双工具去空白后的机械一致性；仅移除几何确认的末端页码。'
                           '白色无描边矩形仅在不覆盖先前文字时豁免。'
                           '不支持图片、可见绘图、表格边框、注释、表单、白色文字和ExtGState；'
                           '不保证识别无边框表格，不构成视觉、法律完整性或适用性审阅。'}
    if exceptions:
        manifest['bounds'] = {'removed_footer_clip_exceptions':exceptions,
                              'body_glyph_clip_checks_unchanged':True,
                              'physical_page_bounds_checked_for_all_glyphs':True}
        manifest['scope'] += '仅双工具均已移除的同坐标页脚数字/横线不检查活动裁剪框，仍检查物理页面范围并单列记录。'
    if any(page.get('verified_neutral_graphics_states') for page in pages):
        manifest['scope'] += 'ExtGState仅精确的Type/AIS=false/BM=Normal/CA=1/ca=1组合例外，逐页留证；其他键或值仍拒绝。'
    return text, manifest


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit('usage: official_pdf.py --worker EXPECTED_TITLE')
    try:
        text, manifest = _extract_local(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[2])
        response = {'text': text, 'manifest': manifest}
    except Exception as exc:
        response = {'error': 'PDF抽取失败：' + str(exc)[:1000]}
    print(json.dumps(response, ensure_ascii=False))
