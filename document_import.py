"""업로드 문서를 로컬에서 PDF로 준비합니다. 정상 변환은 화면에 알리지 않습니다."""
import os
import shutil
import subprocess
import tempfile
import re
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pymupdf
from runtime_paths import background_options

_conversion_lock=threading.Lock()


def find_soffice():
    configured=os.environ.get('SOFFICE_PATH')
    candidates=[configured,shutil.which('soffice'),shutil.which('libreoffice'),
                '/Applications/LibreOffice.app/Contents/MacOS/soffice',
                str(Path.home()/'Applications/LibreOffice.app/Contents/MacOS/soffice')]
    return next((str(path) for path in candidates if path and Path(path).is_file()),None)


def find_node():
    candidates=[os.environ.get('NODE_PATH_EXECUTABLE'),shutil.which('node'),'/opt/homebrew/bin/node','/usr/local/bin/node']
    nvm=Path.home()/'.nvm/versions/node'
    if nvm.exists():
        candidates.extend(str(path) for path in sorted(nvm.glob('*/bin/node'),reverse=True))
    for path in candidates:
        if not path or not Path(path).is_file():
            continue
        try:
            result=subprocess.run([str(path),'--version'],capture_output=True,text=True,timeout=5,**background_options())
            if result.returncode==0 and int(result.stdout.strip().lstrip('v').split('.')[0])>=18:
                return str(path)
        except (ValueError,OSError,subprocess.TimeoutExpired):
            continue
    return None


def render_with_rhwp(node,source,output):
    script=Path(__file__).resolve().parent/'vendor/hwp/scripts/hwp-preview.mjs'
    try:
        result=subprocess.run([node,str(script),str(source),str(output)],capture_output=True,text=True,timeout=180,**background_options())
    except subprocess.TimeoutExpired as error:
        raise ValueError('문서 처리 시간이 초과되었습니다.') from error
    pages=list(output.glob('*.svg'))
    if result.returncode or not pages:
        raise ValueError('한글 문서를 렌더링하지 못했습니다. 이 문서는 PDF로 저장해 올려주세요.')
    def number(path):
        match=re.search(r'-p(\d+)\.svg$',path.name)
        return int(match.group(1)) if match else 0
    with pymupdf.open() as merged:
        for path in sorted(pages,key=number):
            with pymupdf.open(path) as svg:
                data=svg.convert_to_pdf()
            with pymupdf.open(stream=data,filetype='pdf') as page_pdf:
                size=page_pdf[0].rect
                page=merged.new_page(width=size.width*72/96,height=size.height*72/96)
                page.show_pdf_page(page.rect,page_pdf,0)
        return merged.tobytes(garbage=4,deflate=True)


def file_kind(filename,data):
    if data.lstrip().startswith(b'%PDF-'):
        return 'pdf'
    suffix=Path(filename).suffix.lower()
    if suffix in ('.hwp','.hwpx'):
        return suffix[1:]
    raise ValueError('PDF 또는 한글 문서를 선택해 주세요.')


def valid_pdf(data,require_content=False):
    with pymupdf.open(stream=data,filetype='pdf') as document:
        if document.needs_pass or not len(document):
            raise ValueError('암호가 없고 페이지가 있는 문서가 필요합니다.')
        if require_content and not any(page.get_text().strip() or page.get_images() or page.get_drawings() for page in document):
            raise ValueError('변환 결과가 비어 있어 등록하지 않았습니다.')


def to_pdf(filename,data):
    kind=file_kind(filename,data)
    name=Path(filename).with_suffix('.pdf').name
    if kind=='pdf':
        valid_pdf(data)
        return name,data
    if kind=='hwp' and not data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise ValueError('한글 문서 형식을 확인할 수 없습니다.')
    if kind=='hwpx':
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                if not any(item.lower().startswith('contents/') for item in archive.namelist()):
                    raise ValueError('한글 문서 형식을 확인할 수 없습니다.')
        except zipfile.BadZipFile as error:
            raise ValueError('한글 문서가 손상되어 읽을 수 없습니다.') from error
    node=find_node()
    executable=find_soffice()
    renderer=Path(__file__).resolve().parent/'vendor/hwp/scripts/hwp-preview.mjs'
    if not node and not executable:
        raise ValueError('한글 문서를 처리하려면 Node.js 18 이상이 필요합니다. Node.js를 설치하고 앱을 다시 실행해 주세요.')
    with _conversion_lock,tempfile.TemporaryDirectory(prefix='study-import-') as directory:
        root=Path(directory)
        source=root/f'input.{kind}'
        source.write_bytes(data)
        output=root/'converted'
        output.mkdir()
        if node and renderer.exists():
            try:
                pdf=render_with_rhwp(node,source,output)
                valid_pdf(pdf,require_content=True)
                return name,pdf
            except ValueError:
                if not executable:
                    raise
        if not executable:
            raise ValueError('앱의 vendor/hwp 폴더가 없습니다. 업데이트 파일을 모두 복사해 주세요.')
        try:
            result=subprocess.run([executable,'--headless','--norestore','--infilter=Hwp2002_File','--convert-to','pdf:writer_pdf_Export','--outdir',str(output),str(source)],capture_output=True,text=True,timeout=180,**background_options())
        except subprocess.TimeoutExpired as error:
            raise ValueError('문서 처리 시간이 초과되었습니다. PDF로 저장해 다시 올려주세요.') from error
        converted=output/'input.pdf'
        if result.returncode or not converted.exists():
            raise ValueError('한글 문서를 PDF로 변환하지 못했습니다. LibreOffice의 H2Orestart 확장과 Java 설정을 확인하거나 PDF로 저장해 올려주세요.')
        pdf=converted.read_bytes()
        valid_pdf(pdf,require_content=True)
        return name,pdf
