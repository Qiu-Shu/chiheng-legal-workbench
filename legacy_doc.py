"""Convert bounded legacy Word originals with configured or installed LibreOffice."""
import subprocess
import tempfile
from pathlib import Path
from local_settings import resolve_soffice

SOFFICE = None


def convert_legacy_doc(payload):
    if not payload.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) or len(payload) > 10_000_000:
        raise ValueError('不是支持的OLE旧DOC原件或超过10MB')
    soffice = str(resolve_soffice(SOFFICE))
    outputs = []
    with tempfile.TemporaryDirectory(prefix='chiheng-doc-') as tmp:
        root = Path(tmp)
        source = root / 'original.doc'
        source.write_bytes(payload)
        for kind in ('docx', 'txt:Text'):
            result = subprocess.run([soffice, '--headless', '--convert-to', kind, '--outdir', tmp,
                                     str(source)], capture_output=True, timeout=30)
            target = source.with_suffix('.' + kind.split(':')[0])
            if result.returncode or not target.exists() or not 0 < target.stat().st_size <= 50_000_000:
                raise ValueError('旧DOC本机转换失败；未采纳不完整输出')
            outputs.append(target.read_bytes())
    return outputs[0], outputs[1].decode('utf-8-sig')
