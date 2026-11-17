import json
import re
from exam_info import normalize_exam
from answer_archive import SYMBOL_MASKS, load_archive

def load_questions(job):
    questions=[]
    for path in sorted(job.glob('page-*/output/questions-with-images.md')):
        page=int(path.parent.parent.name.split('-')[1])
        state_path=path.parent.parent/'state.json'
        state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        if not state.get('references'):
            continue
        text=path.read_text(encoding='utf-8')
        matches=list(re.finditer(r'(?m)^(\d+)[.)]\s+(.+)$',text))
        metadata=path.parent.parent/'exam-metadata.json'
        exam=json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {}
        number_map_path=path.parent.parent/'question-number-map.json'
        number_map={item['number']:item['source_number'] for item in json.loads(number_map_path.read_text(encoding='utf-8'))} if number_map_path.exists() else {}
        warning_path=path.parent.parent/'extraction-warnings.json'
        warnings=json.loads(warning_path.read_text(encoding='utf-8')) if warning_path.exists() and not state.get('manual') else []
        for index,match in enumerate(matches):
            block=text[match.start():matches[index+1].start() if index+1<len(matches) else len(text)]
            choice_matches=list(re.finditer(r'(?m)^- \[[ xX]\]\s*(.*)$',block))
            stem=block[:choice_matches[0].start()].strip() if choice_matches else block.strip()
            choices=[]
            for i,choice in enumerate(choice_matches):
                value=block[choice.start():choice_matches[i+1].start() if i+1<len(choice_matches) else len(block)]
                value=re.sub(r'^- \[[ xX]\]\s*','',value).strip()
                choices.append(value)
            questions.append({'number':int(match.group(1)),'page':page,'stem':stem,'choices':choices,'folder':path.parent,'exam':normalize_exam(exam.get('year'),exam.get('term')),'warnings':[warning['message'] for warning in warnings if number_map.get(int(match.group(1)),int(match.group(1))) in warning.get('questions',[])]})
    return questions

def parse_answers(raw):
    value=re.sub(r'[\s,，;]+','',raw)
    if value and not re.fullmatch(r'[1-9A-K?]+',value):
        raise ValueError('정답 번호 1~9, 복수 정답 A~K, 미확정 ?만 입력해 주세요. 공백과 쉼표는 사용할 수 있습니다.')
    return {str(index):None if answer=='?' else int(answer) if answer.isdigit() else answer
            for index,answer in enumerate(value,1)}

def answer_correct(selected, answer):
    if selected is None or answer is None:
        return None
    if isinstance(answer, str) and answer in SYMBOL_MASKS:
        return int(isinstance(selected, int) and 1 <= selected <= 4 and bool(SYMBOL_MASKS[answer] & (1 << (selected - 1))))
    return int(selected == answer)

class QuizStore:
    def __init__(self,catalog):
        self.catalog=catalog
        with catalog.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS answer_keys(material TEXT PRIMARY KEY, answers TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quiz_attempts(material TEXT NOT NULL, question TEXT NOT NULL, selected INTEGER, PRIMARY KEY(material,question));
                CREATE TABLE IF NOT EXISTS practice_rounds(id INTEGER PRIMARY KEY AUTOINCREMENT, material TEXT NOT NULL, number INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(material,number));
                CREATE TABLE IF NOT EXISTS practice_attempts(round_id INTEGER NOT NULL, question TEXT NOT NULL, selected INTEGER, correct INTEGER, answer INTEGER, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(round_id,question));
                CREATE TABLE IF NOT EXISTS practice_migrations(material TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS explanation_notes(material TEXT NOT NULL, question TEXT NOT NULL, note TEXT NOT NULL, PRIMARY KEY(material,question));
                CREATE TABLE IF NOT EXISTS explanations(material TEXT NOT NULL, question TEXT NOT NULL, chapter TEXT NOT NULL, offset INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '', PRIMARY KEY(material,question,chapter,offset));
            ''')
        with catalog.connect() as db:
            columns={row['name'] for row in db.execute('PRAGMA table_info(answer_keys)')}
            if 'origin' not in columns:
                db.execute("ALTER TABLE answer_keys ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual'")

    def apply_archive(self,material):
        """Use a unique course/year/term key; preserve explicit manual answers."""
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT answers,origin FROM answer_keys WHERE material=?',(material,)).fetchone()
            if existing and existing['origin']=='manual':
                return False
            item=db.execute('SELECT m.exam_year,m.exam_term,s.name FROM materials m JOIN subjects s ON s.id=m.subject_id WHERE m.id=?',(material,)).fetchone()
            keys=()
            if item:
                exam=normalize_exam(item['exam_year'],item['exam_term'])
                if exam['term'] in ('1학기','2학기'):
                    keys=load_archive().find(exam['year'],int(exam['term'][0]),item['name'])
            if len(keys)!=1 or not keys[0].masks:
                if existing:
                    db.execute('DELETE FROM answer_keys WHERE material=? AND origin=?',(material,'archive'))
                return False
            symbols={mask:symbol for symbol,mask in SYMBOL_MASKS.items()}
            answers={str(i):None if mask==0 else int(symbols[mask]) if symbols[mask].isdigit() else symbols[mask]
                     for i,mask in enumerate(keys[0].masks,1)}
            encoded=json.dumps(answers)
            if existing and existing['answers']==encoded:
                return True
            db.execute("INSERT INTO answer_keys(material,answers,origin) VALUES(?,?,'archive') ON CONFLICT(material) DO UPDATE SET answers=excluded.answers,origin=excluded.origin",(material,encoded))
            self.grade_pending(db,material,answers)
            return True

    def grade_pending(self,db,material,answers):
        rows=db.execute('SELECT a.round_id,a.question,a.selected FROM practice_attempts a JOIN practice_rounds r ON r.id=a.round_id WHERE r.material=? AND a.correct IS NULL AND a.selected IS NOT NULL',(material,)).fetchall()
        for row in rows:
            answer=answers.get(row['question'].split(':')[-1])
            if answer is not None:
                db.execute('UPDATE practice_attempts SET correct=?,answer=? WHERE round_id=? AND question=?',(answer_correct(row['selected'],answer),answer,row['round_id'],row['question']))

    def answers(self,material):
        with self.catalog.connect() as db:
            row=db.execute('SELECT answers FROM answer_keys WHERE material=?',(material,)).fetchone()
        return json.loads(row['answers']) if row else {}

    def answer_origin(self,material):
        with self.catalog.connect() as db:
            row=db.execute('SELECT origin FROM answer_keys WHERE material=?',(material,)).fetchone()
        return row['origin'] if row else None

    def save_answers(self,material,raw):
        answers=parse_answers(raw)
        with self.catalog.connect() as db:
            db.execute("INSERT INTO answer_keys(material,answers,origin) VALUES(?,?,'manual') ON CONFLICT(material) DO UPDATE SET answers=excluded.answers,origin=excluded.origin",(material,json.dumps(answers)))
            self.grade_pending(db,material,answers)
        return answers

    def rounds(self,material):
        with self.catalog.connect() as db:
            db.execute('INSERT INTO practice_rounds(material,number) SELECT ?,1 WHERE NOT EXISTS(SELECT 1 FROM practice_rounds WHERE material=? AND number=1)',(material,material))
            if not db.execute('SELECT 1 FROM practice_migrations WHERE material=?',(material,)).fetchone():
                first=db.execute('SELECT id FROM practice_rounds WHERE material=? AND number=1',(material,)).fetchone()['id']
                key=db.execute('SELECT answers FROM answer_keys WHERE material=?',(material,)).fetchone()
                answers=json.loads(key['answers']) if key else {}
                for row in db.execute('SELECT question,selected FROM quiz_attempts WHERE material=?',(material,)).fetchall():
                    answer=answers.get(row['question'].split(':')[-1])
                    correct=answer_correct(row['selected'],answer) if row['selected'] is not None and answer is not None else None
                    db.execute('INSERT OR IGNORE INTO practice_attempts(round_id,question,selected,correct,answer) VALUES(?,?,?,?,?)',(first,row['question'],row['selected'],correct,answer))
                db.execute('INSERT INTO practice_migrations VALUES(?)',(material,))
            return [dict(row) for row in db.execute('SELECT * FROM practice_rounds WHERE material=? ORDER BY number',(material,))]

    def new_round(self,material):
        self.rounds(material)
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            number=db.execute('SELECT MAX(number)+1 FROM practice_rounds WHERE material=?',(material,)).fetchone()[0]
            cursor=db.execute('INSERT INTO practice_rounds(material,number) VALUES(?,?)',(material,number))
            return cursor.lastrowid

    def records(self,round_id):
        with self.catalog.connect() as db:
            return {row['question']:dict(row) for row in db.execute('SELECT * FROM practice_attempts WHERE round_id=?',(round_id,))}

    def select(self,material,question,value,round_id=None):
        if round_id is None:
            round_id=self.rounds(material)[0]['id']
        answer=self.answers(material).get(question.split(':')[-1])
        correct=answer_correct(value,answer)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO practice_attempts(round_id,question,selected,correct,answer) VALUES(?,?,?,?,?) ON CONFLICT(round_id,question) DO UPDATE SET selected=excluded.selected,correct=excluded.correct,answer=excluded.answer,updated_at=CURRENT_TIMESTAMP',(round_id,question,value,correct,answer))

    def note(self,material,question):
        with self.catalog.connect() as db:
            row=db.execute('SELECT note FROM explanation_notes WHERE material=? AND question=?',(material,question)).fetchone()
            if row is None:
                row=db.execute('SELECT note FROM explanations WHERE material=? AND question=? LIMIT 1',(material,question)).fetchone()
        return row['note'] if row else ''

    def replace_links(self,material,question,chapters,pages,note):
        records=[]
        for page in sorted(set(pages)):
            chapter=next((c for c in chapters if c['start']<=page<=c['end']),None)
            if chapter is None:
                raise ValueError('선택한 해설 페이지를 찾을 수 없습니다.')
            records.append((material,question,chapter['id'],page-chapter['start'],note))
        with self.catalog.connect() as db:
            db.execute('INSERT INTO explanation_notes VALUES(?,?,?) ON CONFLICT(material,question) DO UPDATE SET note=excluded.note',(material,question,note))
            db.execute('DELETE FROM explanations WHERE material=? AND question=?',(material,question))
            db.executemany('INSERT INTO explanations VALUES(?,?,?,?,?)',records)

    def related(self,subject,chapter,offset=None):
        query='SELECT e.material,e.question FROM explanations e JOIN materials m ON m.id=e.material WHERE m.subject_id=? AND e.chapter=?'
        params=[subject,chapter]
        if offset is not None:
            query+=' AND e.offset=?'
            params.append(offset)
        with self.catalog.connect() as db:
            rows=db.execute(query,params).fetchall()
        result={}
        for row in rows:
            result.setdefault(row['material'],set()).add(row['question'])
        return result

    def links(self,material,question):
        with self.catalog.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM explanations WHERE material=? AND question=?',(material,question))]
