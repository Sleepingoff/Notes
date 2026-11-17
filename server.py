"""HTML/CSS/JS 화면용 로컬 API. 기존 workspace를 그대로 사용합니다."""
import argparse
import hmac
import os
import base64
import json
import mimetypes
import uuid
import math
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse,quote

import pymupdf
from answer_archive import load_archive
import ai_settings
import region_extraction
from runtime_paths import workspace_path
from catalog import Catalog
from core import safe_image,question_span,replace_question,export_zip
from question_editing import read_page, completed_page, save_page
from background_jobs import enqueue,list_jobs,retry_job,ensure_worker
from study_data import QuizStore,load_questions
from annotation_data import AnnotationStore,export_pdf as annotated_pdf,page_preview
from document_import import to_pdf
from lecture_data import LectureStore
import hashlib

BASE=Path(__file__).resolve().parent
CAT=Catalog(workspace_path(BASE))
QUIZ=QuizStore(CAT)
INK=AnnotationStore(CAT)
LECTURES=LectureStore(CAT)


def material(identifier):
    with CAT.connect() as db:
        row=db.execute('SELECT * FROM materials WHERE id=?',(identifier,)).fetchone()
    if not row:raise ValueError('자료를 찾을 수 없습니다.')
    return dict(row)


def latest(subject):
    return {task['material_id']:task for task in list_jobs(BASE,subject)}


def bank_task(item,ready=False):
    task=latest(item['subject_id']).get(item['id'])
    if not task:raise ValueError('추출 작업이 없습니다.')
    if ready and not load_questions(Path(task['output_path'])):
        raise ValueError('아직 추출이 완료되지 않았습니다.')
    return task


def bundle(subject):
    result=CAT.bundle(subject)
    if not result:raise ValueError('강의자료가 없습니다.')
    return result


def chapter_at(data,page):
    if not 1<=page<=data['pages']:raise ValueError('페이지 범위를 확인해 주세요.')
    return next(c for c in data['chapters'] if c['start']<=page<=c['end'])


def related(subject,page,scope='page'):
    data=bundle(subject);chapter=chapter_at(data,page)
    mapping=QUIZ.related(subject,chapter['id'],None if scope=='lesson' else page-chapter['start'])
    tasks=latest(subject);result={}
    for identifier,ids in mapping.items():
        task=tasks.get(identifier)
        if task:
            available={f"{q['page']}:{q['number']}" for q in load_questions(Path(task['output_path']))}
            keep=ids & available
            if keep:result[identifier]=sorted(keep)
    return result


def decode_upload(upload):
    raw=base64.b64decode(upload['data'],validate=True)
    filename,pdf=to_pdf(upload['name'],raw)
    return filename,pdf,hashlib.sha256(raw).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def send(self,data,status=200,mime='application/json; charset=utf-8',filename=None):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store' if self.path.startswith('/api/') else 'no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        if filename:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename))
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        try:self.get()
        except (ValueError,KeyError,TypeError) as error:self.send({'error':str(error)},400)
        except Exception as error:self.send({'error':str(error)},500)

    def authorized(self):
        expected=os.environ.get('NOTES_AUTH_TOKEN','')
        return not expected or hmac.compare_digest(self.headers.get('X-Notes-Token',''),expected)

    def get(self):
        parsed=urlparse(self.path);path=parsed.path
        query={key:value[0] for key,value in parse_qs(parsed.query).items()}
        if path.startswith('/api/') and not self.authorized():return self.send({'error':'앱 인증이 필요합니다.'},401)
        if path=='/api/settings/ai':return self.send(ai_settings.load(CAT.root))
        if path=='/api/settings/ai/status':return self.send(ai_settings.status(CAT.root))
        if path=='/api/subjects':return self.send(CAT.subjects())
        if path=='/api/subject':
            subject=query['id'];data=CAT.bundle(subject)
            subject_row=next((row for row in CAT.subjects() if row['id']==subject),None)
            if subject_row is None:raise ValueError('과목을 찾을 수 없습니다.')
            banks=CAT.materials(subject,'bank');tasks=latest(subject)
            for item in banks:
                task=tasks.get(item['id']);item['task']=task
                item['ready']=bool(task and load_questions(Path(task['output_path'])))
                item['incompletePages']=[page for page in range(1,item['pages']+1) if not completed_page(task['output_path'],page)] if task else []
            return self.send({'bundle':{k:v for k,v in data.items() if k!='path'} if data else None,'banks':banks,'legacyLectures':CAT.materials(subject,'lecture'),'lecturePlan':LECTURES.plan(subject),'answerKeys':load_archive().tables(subject_row['name'])})
        if path=='/api/explanation-note':
            material(query['bank']);return self.send({'note':QUIZ.note(query['bank'],query['question'])})
        if path=='/api/lecture/page':
            data=bundle(query['subject']);page=int(query.get('page') or 1);chapter_at(data,page)
            if query.get('annotated')=='1':image=page_preview(CAT,data,page)
            else:
                with pymupdf.open(data['path']) as pdf:image=pdf[page-1].get_pixmap(dpi=120,alpha=False).tobytes('png')
            return self.send(image,mime='image/png')
        if path=='/api/lecture/annotations':
            data=bundle(query['subject']);page=int(query.get('page') or 1);chapter=chapter_at(data,page)
            saved=INK.get(query['subject'],chapter['id'],page-chapter['start'])
            return self.send({**saved,'pageKey':f"{query['subject']}:{chapter['id']}:{page-chapter['start']}"})
        if path=='/api/lecture/pdf':
            data=bundle(query['subject'])
            pdf=annotated_pdf(CAT,data) if query.get('annotated')=='1' else data['path'].read_bytes()
            return self.send(pdf,mime='application/pdf',filename='강의자료-필기.pdf' if query.get('annotated')=='1' else '강의자료.pdf')
        if path=='/api/related':return self.send(related(query['subject'],int(query.get('page') or 1),query.get('scope','page')))
        if path=='/api/quiz':
            item=material(query['bank']);task=bank_task(item,ready=True)
            questions=load_questions(Path(task['output_path']))
            if query.get('lecturePage'):
                ids=related(item['subject_id'],int(query['lecturePage']),query.get('scope','page')).get(item['id'],[])
                questions=[q for q in questions if f"{q['page']}:{q['number']}" in ids]
            result=[]
            for q in questions:
                result.append({k:v for k,v in q.items() if k!='folder'}|{'id':f"{q['page']}:{q['number']}"})
            QUIZ.apply_archive(item['id'])
            rounds=QUIZ.rounds(item['id'])
            for row in rounds:row['records']=QUIZ.records(row['id'])
            return self.send({'material':item,'questions':result,'rounds':rounds,'answers':QUIZ.answers(item['id']),'answerOrigin':QUIZ.answer_origin(item['id'])})
        if path=='/api/explanations':
            item=material(query['bank']);data=CAT.bundle(item['subject_id']);links=QUIZ.links(item['id'],query['question']);result=[]
            if data:
                for link in links:
                    chapter=next((c for c in data['chapters'] if c['id']==link['chapter']),None)
                    if chapter and chapter['start']+link['offset']<=chapter['end']:
                        result.append({**link,'page':chapter['start']+link['offset'],'title':chapter['title']})
            return self.send(result)
        if path in ('/api/question/image','/api/question/page','/api/question/raw','/api/question/zip'):
            item=material(query['bank']);task=bank_task(item);job=Path(task['output_path'])
            if path.endswith('/zip'):
                return self.send(export_zip(job,list(range(1,item['pages']+1))),mime='application/zip',filename='문제.zip')
            page=int(query['page'])
            if not 1<=page<=item['pages']:raise ValueError('페이지 범위를 확인해 주세요.')
            folder=job/f'page-{page:03d}'/'output'
            if path.endswith('/image'):
                image=safe_image(folder,query['file'])
                if not image:raise ValueError('이미지가 없습니다.')
                return self.send(image.read_bytes(),mime=mimetypes.guess_type(image.name)[0] or 'image/png')
            if path.endswith('/page'):
                with pymupdf.open(CAT.pdf_path(item)) as pdf:image=pdf[page-1].get_pixmap(dpi=120,alpha=False).tobytes('png')
                return self.send(image,mime='image/png')
            text=read_page(job,page)
            warnings=job/f'page-{page:03d}'/'extraction-warnings.json'
            review=json.loads(warnings.read_text(encoding='utf-8')) if warnings.exists() else []
            if query.get('mode')=='page':
                earlier=load_questions(job)
                suggested=max((q['number'] for q in earlier if q['page']<page),default=0)+1
                return self.send({'text':text,'suggestedNumber':suggested,'warnings':review})
            first,last=question_span(text,int(query['number']))
            return self.send({'text':text[first:last].strip(),'warnings':review})
        if path.startswith('/api/'):return self.send({'error':'없는 API입니다.'},404)
        if path.startswith('/annotation_component/'):
            root=BASE/'annotation_component';relative=path[len('/annotation_component/'):]
        else:root=BASE/'web';relative='index.html' if path=='/' else path.lstrip('/')
        target=(root/relative).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():return self.send({'error':'파일이 없습니다.'},404)
        return self.send(target.read_bytes(),mime=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.send({'error':'허용되지 않은 요청입니다.'},403)
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=280*1024*1024:raise ValueError('요청 크기를 확인해 주세요.')
            data=json.loads(self.rfile.read(length));self.post(urlparse(self.path).path,data)
        except (ValueError,KeyError,TypeError) as error:self.send({'error':str(error)},400)
        except Exception as error:self.send({'error':str(error)},500)

    def post(self,path,data):
        if not self.authorized():return self.send({'error':'앱 인증이 필요합니다.'},401)
        if path=='/api/settings/ai':return self.send(ai_settings.save(CAT.root,data))
        if path=='/api/subject':return self.send({'id':CAT.add_subject(data['name'])})
        if path=='/api/subject/rename':
            CAT.rename_subject(data['id'],data['name']);return self.send({'ok':True,'answerKeys':load_archive().tables(data['name'])})
        if path=='/api/subject/delete':
            with LECTURES.lock:
                CAT.delete_subject(data['id'])
            return self.send({'ok':True})
        if path=='/api/lecture/auto':
            uploads=[decode_upload(upload)[1] for upload in data.get('uploads',[])]
            return self.send(LECTURES.save(data['subject'],data['order'],uploads))
        if path=='/api/lecture/merge':
            subject=data['subject'];old=CAT.bundle(subject);uploads=[decode_upload(u) for u in data.get('uploads',[])]
            parts=[]
            for row in data['order']:
                if row.get('chapter'):
                    chapter=next(c for c in (old['chapters'] if old else []) if c['id']==row['chapter'])
                    parts.append({'title':row['title'],'path':old['path'],'first':chapter['start']-1,'last':chapter['end']-1,'chapter_id':chapter['id']})
                elif row.get('legacy'):
                    item=material(row['legacy'])
                    if item['subject_id']!=subject or item['kind']!='lecture':raise ValueError('강의자료를 확인해 주세요.')
                    parts.append({'title':row['title'],'path':CAT.pdf_path(item)})
                else:parts.append({'title':row['title'],'data':uploads[int(row['upload'])][1]})
            CAT.merge_lectures(subject,parts);return self.send({'ok':True})
        if path=='/api/bank/upload':
            result=[]
            for upload in data['files']:
                filename,pdf,digest=decode_upload(upload)
                item,created=CAT.register(data['subject'],'bank',filename,pdf,source_digest=digest)
                task=enqueue(BASE,item);result.append({'id':item['id'],'created':created,'task':task['id']})
            return self.send(result)
        if path=='/api/material/meta':
            material(data['bank']);CAT.update_exam(data['bank'],data.get('year',0),data.get('term',''));return self.send({'ok':True})
        if path=='/api/job/retry':retry_job(BASE,data['id']);return self.send({'ok':True})
        if path=='/api/answers':material(data['bank']);return self.send(QUIZ.save_answers(data['bank'],data['raw']))
        if path=='/api/round':material(data['bank']);return self.send({'id':QUIZ.new_round(data['bank'])})
        if path=='/api/select':
            item=material(data['bank']);round_id=int(data['round'])
            if round_id not in [row['id'] for row in QUIZ.rounds(item['id'])]:raise ValueError('풀이 회차가 잘못되었습니다.')
            QUIZ.apply_archive(item['id'])
            QUIZ.select(item['id'],data['question'],data.get('value'),round_id)
            return self.send(QUIZ.records(round_id).get(data['question'],{}))
        if path=='/api/explanations':
            item=material(data['bank']);current=bundle(item['subject_id'])
            QUIZ.replace_links(item['id'],data['question'],current['chapters'],data['pages'],data.get('note',''));return self.send({'ok':True})
        if path=='/api/lecture/annotations':
            current=bundle(data['subject']);page=int(data['page']);chapter=chapter_at(current,page)
            INK.save(data['subject'],chapter['id'],page-chapter['start'],data['revision'],data['marks']);return self.send({'ok':True})
        if path=='/api/question/reextract':
            item=material(data['bank']);task=bank_task(item)
            page=int(data['page'])
            if not 1<=page<=item['pages']:raise ValueError('페이지 범위를 확인해 주세요.')
            result=region_extraction.extract(CAT.pdf_path(item),page,int(data['number']),data['problem_box'],data.get('image_boxes',[]),Path(task['output_path'])/f'page-{page:03d}'/'output',CAT.root)
            return self.send(result)
        if path=='/api/question/crop':
            item=material(data['bank']);task=bank_task(item)
            page=int(data['page']);box=data['bbox']
            if not 1<=page<=item['pages'] or len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):raise ValueError('이미지 범위를 확인해 주세요.')
            x0,y0,x1,y1=box
            if not (0<=x0<x1<=1000 and 0<=y0<y1<=1000):raise ValueError('이미지 범위는 왼쪽 위부터 오른쪽 아래 순서로 0~1000입니다.')
            filename='manual-'+uuid.uuid4().hex+'.png'
            folder=Path(task['output_path'])/f'page-{page:03d}'/'output'
            folder.mkdir(parents=True,exist_ok=True)
            with pymupdf.open(CAT.pdf_path(item)) as pdf:
                rect=pdf[page-1].rect
                clip=pymupdf.Rect(rect.width*x0/1000,rect.height*y0/1000,rect.width*x1/1000,rect.height*y1/1000)
                pdf[page-1].get_pixmap(dpi=300,clip=clip,alpha=False).save(folder/filename)
            return self.send({'file':filename,'markdown':f'![참고자료]({filename})'})
        if path=='/api/question/edit':
            item=material(data['bank']);task=bank_task(item)
            if not 1<=int(data['page'])<=item['pages']:raise ValueError('페이지 범위를 확인해 주세요.')
            if data.get('mode')=='page':
                numbers=save_page(CAT,task,int(data['page']),data['text'])
                return self.send({'ok':True,'numbers':numbers})
            path=Path(task['output_path'])/f"page-{int(data['page']):03d}"/'output/questions-with-images.md'
            path.write_text(replace_question(path.read_text(encoding='utf-8'),int(data['number']),data['text']),encoding='utf-8');return self.send({'ok':True})
        return self.send({'error':'없는 API입니다.'},404)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    if any(t['status'] in ('queued','running') for t in list_jobs(BASE)):ensure_worker(BASE)
    http=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print('NOTES_READY='+json.dumps({'port':http.server_address[1]}),flush=True)
    print(f'학습 앱: http://127.0.0.1:{http.server_address[1]}',flush=True)
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:http.server_close()
