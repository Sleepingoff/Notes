import json
import math
import re
import pymupdf

class AnnotationStore:
    def __init__(self,catalog):
        self.catalog=catalog
        with catalog.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS page_annotations (
                subject TEXT NOT NULL, chapter TEXT NOT NULL, offset INTEGER NOT NULL,
                revision TEXT NOT NULL, marks TEXT NOT NULL,
                PRIMARY KEY(subject,chapter,offset))''')

    def get(self,subject,chapter,offset):
        with self.catalog.connect() as db:
            row=db.execute('SELECT revision,marks FROM page_annotations WHERE subject=? AND chapter=? AND offset=?',(subject,chapter,offset)).fetchone()
        return {'revision':row['revision'],'marks':json.loads(row['marks'])} if row else {'revision':'','marks':[]}

    def save(self,subject,chapter,offset,revision,marks):
        marks=validate_marks(marks)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO page_annotations VALUES(?,?,?,?,?) ON CONFLICT(subject,chapter,offset) DO UPDATE SET revision=excluded.revision,marks=excluded.marks',(subject,chapter,offset,revision,json.dumps(marks,ensure_ascii=False)))

    def all(self,subject):
        with self.catalog.connect() as db:
            rows=db.execute('SELECT chapter,offset,revision,marks FROM page_annotations WHERE subject=? ORDER BY chapter,offset',(subject,)).fetchall()
        return [dict(row) for row in rows]

def validate_marks(marks):
    if not isinstance(marks,list) or len(marks)>5000:
        raise ValueError('필기 데이터 형식을 확인해 주세요.')
    total=0
    for mark in marks:
        if mark.get('type') not in ('stroke','text'):
            raise ValueError('필기 종류가 잘못되었습니다.')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(mark.get('color',''))):
            raise ValueError('필기 색상이 잘못되었습니다.')
        for name,minimum,maximum in [('width',0.0001,0.1),('opacity',0.05,1)]:
            value=mark.get(name)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
                raise ValueError('필기 크기 또는 투명도가 잘못되었습니다.')
        if mark['type']=='stroke':
            points=mark.get('points')
            if not isinstance(points,list) or not points:
                raise ValueError('획의 위치가 없습니다.')
            total+=len(points)
            for point in points:
                if len(point)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in point):
                    raise ValueError('획의 좌표가 잘못되었습니다.')
        else:
            if not isinstance(mark.get('text'),str) or len(mark['text'])>10000:
                raise ValueError('텍스트 길이를 확인해 주세요.')
            for name in ('x','y'):
                value=mark.get(name)
                if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
                    raise ValueError('텍스트 위치가 잘못되었습니다.')
            for dimension in ('boxWidth','boxHeight'):
                value=mark.get(dimension)
                if value is not None and (not isinstance(value,(int,float)) or not math.isfinite(value) or not .005<=value<=1):
                    raise ValueError('텍스트박스 크기가 잘못되었습니다.')
            size=mark.get('size')
            if not isinstance(size,(int,float)) or not math.isfinite(size) or not 0.005<=size<=0.15:
                raise ValueError('텍스트 크기가 잘못되었습니다.')
    if total>200000:
        raise ValueError('이 페이지의 필기 점이 너무 많습니다. 일부 획을 정리해 주세요.')
    return marks

def draw_marks(page,marks):
    if page.rotation:
        page.remove_rotation()
    width,height=page.rect.width,page.rect.height
    for mark in validate_marks(marks):
        color=tuple(int(mark['color'][i:i+2],16)/255 for i in (1,3,5))
        if mark['type']=='stroke':
            points=[pymupdf.Point(x*width,y*height) for x,y in mark['points']]
            line_width=mark['width']*width
            if len(points)==1:
                page.draw_circle(points[0],line_width/2,color=color,fill=color,stroke_opacity=mark['opacity'],fill_opacity=mark['opacity'])
            else:
                page.draw_polyline(points,color=color,width=line_width,lineCap=1,lineJoin=1,stroke_opacity=mark['opacity'],overlay=True)
        else:
            size=mark['size']*width
            text=mark['text']
            if mark.get('boxWidth'):
                font=pymupdf.Font('korea');lines=[]
                for paragraph in text.split('\n'):
                    line=''
                    for char in paragraph:
                        if line and font.text_length(line+char,fontsize=size)>mark['boxWidth']*width:
                            lines.append(line);line=char
                        else:line+=char
                    lines.append(line)
                limit=max(1,int(mark.get('boxHeight',1)*height/(size*1.35)))
                text='\n'.join(lines[:limit])
            page.insert_text((mark['x']*width,mark['y']*height+size),text,fontsize=size,fontname='korea',color=color,lineheight=1.35,overlay=True)

def page_preview(catalog,bundle,page):
    chapter=next(c for c in bundle['chapters'] if c['start']<=page<=c['end'])
    marks=AnnotationStore(catalog).get(bundle['subject_id'],chapter['id'],page-chapter['start'])['marks']
    with pymupdf.open(bundle['path']) as pdf:
        draw_marks(pdf[page-1],marks)
        return pdf[page-1].get_pixmap(dpi=140,alpha=False).tobytes('png')

def export_pdf(catalog,bundle):
    records={(r['chapter'],r['offset']):json.loads(r['marks']) for r in AnnotationStore(catalog).all(bundle['subject_id'])}
    with pymupdf.open(bundle['path']) as pdf:
        for chapter in bundle['chapters']:
            for page in range(chapter['start'],chapter['end']+1):
                marks=records.get((chapter['id'],page-chapter['start']),[])
                if marks:
                    draw_marks(pdf[page-1],marks)
        return pdf.tobytes(garbage=4,deflate=True)
